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
            file_meta = parser._parse_file_meta(f)

            results.append({
                'filename': f,
                'test_type': file_meta['test_type'] or r.get('test_type', '?'),
                'round': file_meta['round'] or '?',
                'chips': r.get('chips', 0),
                'test_items': r.get('test_items', 0),
                'fail_items': r.get('fail_items', 0)
            })
        ft_files = [f for f in results if f['test_type'] == 'FT']
        qc_files = [f for f in results if f['test_type'] == 'QC']
        return {
            'files': results,
            'ft_files': ft_files,
            'qc_files': qc_files,
            'summary': f'共{len(results)}个数据文件。FT: {len(ft_files)}个, QC: {len(qc_files)}个。'
                       f'⚠️ FT和QC是同一批芯片的不同测试阶段，不要累加芯片数。'
                       f'同一颗芯片在各文件中的chip_id(硅ID)相同。'
        }


class GetSummaryStats:
    """获取整体良率汇总"""
    description = "获取summary.xlsx中各轮次的整体良率和Fail Bin分布。FT和QC良率独立计算。无需参数。"

    def execute(self):
        s = parser.parse_summary()
        result = {}

        # 各轮次独立数据
        rounds_data = {}
        for round_name, rd in s.get('rounds', {}).items():
            fail_bins = [b for b in rd['bins'] if b['result'] == 'FAIL']
            fail_bins.sort(key=lambda x: x['count'], reverse=True)
            file_meta = parser._parse_file_meta(round_name)
            test_type = file_meta.get('test_type')
            rounds_data[round_name] = {
                'test_type': test_type,
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

        # 按 FT/QC 分组汇总良率
        for tt in ('FT', 'QC'):
            tt_rounds = {k: v for k, v in rounds_data.items() if v.get('test_type') == tt}
            if tt_rounds:
                first_round_name = min(tt_rounds.keys())
                first = tt_rounds[first_round_name]
                result[f'{tt}_initial_yield'] = first['yield_rate']
                result[f'{tt}_initial_pass'] = first['pass']
                result[f'{tt}_initial_fail'] = first['fail']
                result[f'{tt}_total'] = first['total_chips']
                # 最终良率 = 初测pass + 后续轮次复测pass（去重）
                # R1/R2 若只复测 fail 芯片，则复测pass数即为新增pass
                # R1/R2 若全量复测，则其pass数可能包含初测已pass的
                # 保守估算：final_pass = R0_pass + sum(后续轮次pass), 上限为 total
                total = first['total_chips']
                r0_pass = first['pass']
                remaining_fail = first['fail']
                final_pass = r0_pass
                sorted_rounds = sorted(tt_rounds.items(), key=lambda x: x[0])
                for rn, rd in sorted_rounds:
                    if rn == first_round_name:
                        continue
                    # 后续轮次 pass 数中，最多有 remaining_fail 个是新增的
                    new_pass = min(rd['pass'], remaining_fail)
                    final_pass += new_pass
                    remaining_fail -= new_pass
                result[f'{tt}_final_yield'] = f'{final_pass/total*100:.1f}%' if total > 0 else 'N/A'
                result[f'{tt}_final_pass'] = final_pass

        result['note'] = 'FT和QC良率独立计算。final_yield 考虑复测通过。'
        return result


class AnalyzeFailItems:
    """深入分析某个数据文件的fail项"""
    description = "分析指定文件的fail测试项。返回fail项详情、规格、fail值及每颗fail芯片的chip_id(硅ID)。参数: filename(文件名)"

    def execute(self, filename):
        r = parser.parse_test_data(filename)
        if 'error' in r:
            return {'error': r['error']}

        file_meta = parser._parse_file_meta(filename)

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
            'test_type': file_meta['test_type'] or r.get('test_type', '?'),
            'round': file_meta['round'] or '?',
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
            file_meta = parser._parse_file_meta(f)
            results.append({
                'filename': f,
                'test_type': file_meta['test_type'] or r.get('test_type', '?'),
                'round': file_meta['round'] or '?',
                'chips': r.get('chips', 0),
                'test_items': r.get('test_items', 0),
                'fail_items': r.get('fail_items', 0)
            })
        # 判断对比维度
        test_types = set(r['test_type'] for r in results if r['test_type'] in ('FT', 'QC'))
        if len(test_types) <= 1:
            dimension = '同类型内对比（初测 vs 复测）'
        else:
            dimension = '跨类型对比（FT vs QC）'
        return {'comparison': results, 'dimension': dimension}


class FindPersistentFails:
    """找出在多个轮次中持续fail的芯片"""
    description = "找出在≥2个轮次中同一测试项持续fail的芯片。FT和QC内部分别判定。单轮次类型(如FT仅R0)的R0 fail也一并列出。参数: min_rounds(可选，默认2)"

    def execute(self, min_rounds=2):
        result = parser.find_persistent_fails(min_rounds=min_rounds)
        if 'error' in result:
            return result

        # 构建精简的 by_test_type 输出
        by_type_out = {}
        for tt, data in result.get('by_test_type', {}).items():
            out = {
                'rounds_analyzed': data['rounds_analyzed'],
                'single_round': data.get('single_round', False),
                'persistent_fail_count': data['persistent_fail_count'],
                'persistent_fail_chips': [
                    {
                        'chip_id': c['chip_id'],
                        'persistent_fail_items': c['persistent_fail_items'][:5],
                        'total_rounds_tested': c['total_rounds_tested'],
                        'round_results': c['round_results']
                    }
                    for c in data['persistent_fail_chips']
                ],
                'persistent_test_items': data.get('persistent_test_items', [])[:10]
            }
            if data.get('single_round'):
                out['note'] = f'{tt}仅有一轮测试，R0结果即为最终结果'
                out['r0_fail_chip_count'] = data.get('r0_fail_chip_count', 0)
                out['r0_fail_test_items'] = data.get('r0_fail_test_items', [])[:10]
            by_type_out[tt] = out

        return {
            'by_test_type': by_type_out,
            'attention_list': result.get('attention_list', []),
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
                for c in result['persistent_fail_chips']
            ],
            'top_persistent_test_items': result.get('persistent_test_items', [])[:10]
        }


class TrackChipAcrossRounds:
    """追踪单颗芯片在所有轮次中的表现"""
    description = "追踪指定芯片(chip_id/硅ID)在所有轮次的测试结果，分FT/QC展示状态变化和最终状态。参数: chip_id(芯片硅ID，如'11292')"

    def execute(self, chip_id):
        result = parser.get_chip_results(chip_id)
        final_status = parser.compute_final_status(chip_id)
        return {
            **result,
            'final_status': final_status
        }


class GenerateCharts:
    """生成分析图表"""
    description = "生成分析图表：Fail项柱状图、良率饼图、良率趋势折线图。保存为PNG文件，返回文件路径供报告引用。无需参数。"

    def execute(self):
        charts = parser.generate_charts()
        return {
            'charts': charts,
            'summary': f'已生成{len(charts)}张图表。在最终报告中用 ![图表名](路径) 引用这些图片。'
        }
