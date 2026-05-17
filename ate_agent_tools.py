"""
Agent用ATE分析工具 — 对接真实ATE数据
"""

import sys, os, json
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from ate_parser import ATEParser

parser = ATEParser()


class ListDataFiles:
    """列出所有ATE数据文件及概要"""
    description = "列出data目录下所有ATE数据文件。返回文件名、测试类型(FT/QC)、轮次(R0/R1/R2)、芯片数、测试项数、fail数。无需参数。"

    def execute(self):
        files = [f for f in parser.list_files() if 'summary' not in f.lower()]
        results = []
        for f in files:
            r = parser.parse_test_data(f)
            fname = os.path.splitext(f)[0]
            parts = fname.split('_')
            round_info = parts[-1] if len(parts) > 1 else '?'
            test_type = r.get('test_type', parts[-2] if len(parts) > 2 else '?')

            results.append({
                'filename': f,
                'test_type': test_type,
                'round': round_info,
                'chips': r.get('chips', 0),
                'test_items': r.get('test_items', 0),
                'fail_items': r.get('fail_items', 0)
            })
        return {
            'files': results,
            'summary': f'共{len(results)}个数据文件，涵盖轮次: {", ".join(sorted(set(r.get("round","?") for r in results)))}。'
                       f'⚠️ 所有文件来自同一批215颗芯片的轮流测试(FT_R0→QC_R0→QC_R1→QC_R2)，不要累加芯片数。'
                       f'同一颗芯片在各文件中的chip_id(硅ID)相同，可用于跨轮次追踪。'
        }


class GetSummaryStats:
    """获取整体良率汇总"""
    description = "获取summary.xlsx中各轮次的整体良率和Fail Bin分布。注意：所有轮次(FT/QC/R0/R1/R2)是同一批215颗芯片的重复测量，不是独立批次。无需参数。"

    def execute(self):
        s = parser.parse_summary()
        result = {
            'note': '⚠️ 所有轮次是同一批芯片(215颗)的重复测量，不是独立批次。不要累加各轮次的芯片数。',
        }

        # 各轮次独立数据
        rounds_data = {}
        for round_name, rd in s.get('rounds', {}).items():
            fail_bins = [b for b in rd['bins'] if b['result'] == 'FAIL']
            fail_bins.sort(key=lambda x: x['count'], reverse=True)
            rounds_data[round_name] = {
                'total_chips': rd['total'],
                'pass': rd['pass'],
                'fail': rd['fail'],
                'yield_rate': rd['yield'],
                'fail_bins': [{'bin': b['sbin'], 'name': b['bin_name'],
                               'count': b['count'],
                               'pct': f"{b['count']/rd['total']*100:.2f}%" if rd['total'] > 0 else 'N/A'}
                              for b in fail_bins]
            }
        result['rounds'] = rounds_data

        # 兼容：FT_R0 作为顶层汇总
        first = s.get('rounds', {}).get('FT_R0', s)
        fail_bins = [b for b in first['bins'] if b['result'] == 'FAIL']
        fail_bins.sort(key=lambda x: x['count'], reverse=True)
        result['total_chips'] = first['total']
        result['pass'] = first['pass']
        result['fail'] = first['fail']
        result['yield_rate'] = first['yield']
        result['fail_bins'] = [{'bin': b['sbin'], 'name': b['bin_name'],
                                'count': b['count'],
                                'pct': f"{b['count']/first['total']*100:.2f}%" if first['total'] > 0 else 'N/A'}
                               for b in fail_bins]
        return result


class AnalyzeFailItems:
    """深入分析某个数据文件的fail项"""
    description = "分析指定文件的fail测试项。返回fail项详情、规格、fail值及每颗fail芯片的chip_id(硅ID)。参数: filename(文件名)"

    def execute(self, filename):
        r = parser.parse_test_data(filename)
        if 'error' in r:
            return {'error': r['error']}

        real_fails = []
        test_item_names = []
        for fa in r.get('fail_analysis', []):
            all_fail_ids = [c['chip_id'] for c in fa.get('fail_chips_sample', [])]
            sample_vals = [c['value'] for c in fa.get('fail_chips_sample', []) if isinstance(c.get('value'), (int, float))]

            fail_info = {
                'test_item': fa['test_item'],
                'spec': fa['spec'],
                'fail_count': fa['fail_count'],
                'fail_rate': fa['fail_rate'],
                'fail_chip_ids': all_fail_ids,
            }
            if sample_vals:
                fail_info['avg_fail_value'] = f"{sum(sample_vals)/len(sample_vals):.4f}"

            real_fails.append(fail_info)
            test_item_names.append(fa['test_item'])

        # 检测系统级异常：如果80%+ fail项是同一测试项族，可能是测试系统问题
        system_anomaly_hint = None
        if len(test_item_names) > 3:
            from collections import Counter
            name_counter = Counter(test_item_names)
            top_name, top_count = name_counter.most_common(1)[0]
            if top_count / len(test_item_names) >= 0.8:
                system_anomaly_hint = (
                    f"⚠️ 系统级异常提示：{top_count}/{len(test_item_names)}（{top_count/len(test_item_names)*100:.0f}%）"
                    f"的fail项为「{top_name}」，这通常是测试系统（探针卡/测量通道/校准）问题，"
                    f"而非芯片物理缺陷。单颗芯片的个体缺陷可能被此系统问题淹没。"
                    f"建议优先排查ATE测试环境。"
                )

        result = {
            'filename': filename,
            'total_chips': r['chips'],
            'total_test_items': r['test_items'],
            'fail_item_count': len(real_fails),
            'note': '⚠️ fail_chip_ids中的ID是chip_id(硅ID)，同一ID在不同轮次文件中是同一颗物理芯片，可用于跨轮次追踪。',
            'top_fails': real_fails[:10]
        }
        if system_anomaly_hint:
            result['system_anomaly_warning'] = system_anomaly_hint
        return result


class CompareFiles:
    """对比多个文件的关键指标"""
    description = "对比多个ATE数据文件。参数: filenames(文件名列表，如['FT_R0.csv','QC_R0.csv'])"

    def execute(self, filenames):
        results = []
        for f in filenames:
            r = parser.parse_test_data(f)
            results.append({
                'filename': f,
                'type': r.get('test_type', '?'),
                'chips': r.get('chips', 0),
                'test_items': r.get('test_items', 0),
                'fail_items': r.get('fail_items', 0)
            })
        return {'comparison': results}


class FindPersistentFails:
    """找出在多个轮次中持续fail的芯片"""
    description = "找出在≥2个轮次中同一测试项持续fail的芯片。这是跨轮次追踪的核心分析，能区分偶发fail和硬件缺陷。参数: min_rounds(可选，至少在几轮中fail，默认2)"

    def execute(self, min_rounds=2):
        result = parser.find_persistent_fails(min_rounds=min_rounds)
        if 'error' in result:
            return result

        # 精简输出，避免信息过载
        chips = result['persistent_fail_chips']
        return {
            'total_chips_analyzed': result['total_chips_analyzed'],
            'persistent_fail_count': result['persistent_fail_count'],
            'min_rounds_threshold': result['min_rounds_threshold'],
            'summary': result['summary'],
            'persistent_chips': [
                {
                    'chip_id': c['chip_id'],
                    'persistent_fail_items': c['persistent_fail_items'][:5],
                    'total_rounds_tested': c['total_rounds_tested'],
                    'round_results': c['round_results']
                }
                for c in chips
            ],
            'top_persistent_test_items': result['persistent_test_items'][:10]
        }


class TrackChipAcrossRounds:
    """追踪单颗芯片在所有轮次中的表现"""
    description = "追踪指定芯片(chip_id/硅ID)在所有轮次(FT_R0/QC_R0/QC_R1/QC_R2)的测试结果，包括每轮的pass/fail状态和fail项详情。参数: chip_id(芯片硅ID，如'11292')"

    def execute(self, chip_id):
        result = parser.get_chip_results(chip_id)
        return result
