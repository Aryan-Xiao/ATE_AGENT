"""
Agent用ATE分析工具 — 对接真实ATE数据
"""

import sys, os, json, logging
from collections import Counter, defaultdict
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from ate_parser import ATEParser

log = logging.getLogger("ate_tools")

parser = ATEParser()


class ListDataFiles:
    """列出所有ATE数据文件及概要"""
    description = "列出data目录下所有ATE数据文件。返回文件名、测试类型(FT/QC)、轮次(R0/R1/R2)、芯片数、测试项数、fail数。无需参数。"

    def execute(self):
        log.debug("ListDataFiles 执行")
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
        log.debug("GetSummaryStats 执行")
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
        log.info("AnalyzeFailItems: %s", filename)
        if not filename or not isinstance(filename, str):
            return {'error': '参数 filename 必须是非空字符串'}
        available = [f for f in parser.list_files() if f.endswith('.csv')]
        if filename not in available:
            return {'error': f'文件不存在: {filename}，可用文件: {", ".join(available[:5])}'}
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
    description = "对比多个ATE数据文件，含fail项重叠分析和fail芯片群体一致性。参数: filenames(文件名列表，如['FT_R0.csv','QC_R0.csv'])"

    def execute(self, filenames):
        log.info("CompareFiles: %s", filenames)
        if not filenames or not isinstance(filenames, list):
            return {'error': '参数 filenames 必须是非空数组，如 ["FT_R0.csv", "QC_R0.csv"]'}
        available = [f for f in parser.list_files() if f.endswith('.csv')]
        missing = [f for f in filenames if f not in available]
        if missing:
            return {'error': f'文件不存在: {", ".join(missing)}，可用文件: {", ".join(available[:5])}'}
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
                'fail_items': r.get('fail_items', 0),
                '_fail_item_names': {fa['test_item'] for fa in r.get('fail_analysis', [])},
                '_fail_chip_ids': {c['chip_id'] for fa in r.get('fail_analysis', []) for c in fa.get('fail_chips_sample', [])}
            })

        # 判断对比维度
        test_types = set(r['test_type'] for r in results if r['test_type'] in ('FT', 'QC'))
        if len(test_types) <= 1:
            dimension = '同类型内对比（初测 vs 复测）'
        else:
            dimension = '跨类型对比（FT vs QC）'

        # fail 项重叠分析
        fail_overlap = {}
        all_fail_names = [r['_fail_item_names'] for r in results]
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                shared = all_fail_names[i] & all_fail_names[j]
                only_i = all_fail_names[i] - all_fail_names[j]
                only_j = all_fail_names[j] - all_fail_names[i]
                key = f"{results[i]['filename']} vs {results[j]['filename']}"
                fail_overlap[key] = {
                    'shared_fail_items': sorted(shared)[:20],
                    'shared_count': len(shared),
                    'only_in_first': sorted(only_i)[:10],
                    'only_in_first_count': len(only_i),
                    'only_in_second': sorted(only_j)[:10],
                    'only_in_second_count': len(only_j),
                }

        # fail 芯片群体一致性
        chip_overlap = {}
        all_fail_chips = [r['_fail_chip_ids'] for r in results]
        for i in range(len(results)):
            for j in range(i + 1, len(results)):
                shared = all_fail_chips[i] & all_fail_chips[j]
                key = f"{results[i]['filename']} vs {results[j]['filename']}"
                chip_overlap[key] = {
                    'shared_fail_chips': sorted(shared)[:20],
                    'shared_count': len(shared),
                    'first_fail_count': len(all_fail_chips[i]),
                    'second_fail_count': len(all_fail_chips[j]),
                }

        # 清理内部字段
        for r in results:
            del r['_fail_item_names']
            del r['_fail_chip_ids']

        return {
            'comparison': results,
            'dimension': dimension,
            'fail_overlap': fail_overlap,
            'chip_overlap': chip_overlap,
        }


class FindPersistentFails:
    """找出在多个轮次中持续fail的芯片"""
    description = "找出在≥2个轮次中同一测试项持续fail的芯片。FT和QC内部分别判定。单轮次类型(如FT仅R0)的R0 fail也一并列出。参数: min_rounds(可选，默认2)"

    def execute(self, min_rounds=2):
        log.info("FindPersistentFails: min_rounds=%d", min_rounds)
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
            'top_persistent_test_items': result.get('persistent_test_items', [])[:10],
            'fail_trend_analysis': result.get('fail_trend_analysis', {})
        }


class TrackChipAcrossRounds:
    """追踪单颗芯片在所有轮次中的表现"""
    description = "追踪指定芯片(chip_id/硅ID)在所有轮次的测试结果，分FT/QC展示状态变化和最终状态。参数: chip_id(芯片硅ID，如'11292')"

    def execute(self, chip_id):
        log.info("TrackChipAcrossRounds: chip_id=%s", chip_id)
        if not chip_id or not isinstance(chip_id, (str, int)):
            return {'error': '参数 chip_id 必须是非空字符串或整数，如 "11292"'}
        chip_id = str(chip_id).strip()
        result = parser.get_chip_results(chip_id)
        final_status = parser.compute_final_status(chip_id)
        return {
            **result,
            'final_status': final_status
        }


class ValidateData:
    """数据完整性校验"""
    description = "校验ATE数据完整性：芯片数跨轮次一致性、chip_id缺失轮次、测试项数量变化、异常值检测。无需参数。建议在分析最开始调用。"

    def execute(self):
        log.info("ValidateData 执行")
        files = [f for f in parser.list_files() if f.endswith('.csv')]
        if not files:
            return {'error': '没有找到CSV数据文件'}

        warnings = []

        # 1. 各文件基本信息
        file_info = {}
        for f in files:
            struct = parser._parse_csv_structure(f)
            if 'error' in struct:
                warnings.append({'level': 'error', 'type': '文件解析失败', 'detail': f'{f}: {struct["error"]}'})
                continue
            meta = parser._parse_file_meta(f)
            # 从结构缓存估算芯片数（数据行数）
            chips_estimate = struct['rows'] - struct['data_head_row'] - 1
            file_info[f] = {
                'test_type': meta.get('test_type'),
                'round': meta.get('round'),
                'chips_estimate': max(0, chips_estimate),
                'test_items': len(struct.get('test_items', [])),
                'chip_ids': set(),
            }
            # 收集每个文件中的 chip_id
            data = struct['data']
            rows = struct['rows']
            cols = struct['cols']
            chip_id_col = struct['chip_id_col']
            data_head_row = struct['data_head_row']
            meta_cols = struct['meta_cols']
            for rr in range(data_head_row + 1, rows):
                vals = [data.get((rr, c), '') for c in range(min(8, cols))]
                if all(v == '' or v == 'nan' for v in vals):
                    continue
                chip_id_raw = data.get((rr, chip_id_col), '')
                part_id_val = next((data.get((rr, c), '') for c, h in meta_cols.items() if h == 'PART_ID'), '')
                chip_id, _ = parser._extract_chip_id(chip_id_raw, part_id_val, f)
                file_info[f]['chip_ids'].add(chip_id)

        # 2. 同 test_type 内芯片数一致性
        type_chips = defaultdict(list)
        for f, info in file_info.items():
            if info['test_type']:
                type_chips[info['test_type']].append((f, len(info['chip_ids'])))

        for tt, entries in type_chips.items():
            counts = [c for _, c in entries]
            if len(set(counts)) > 1:
                detail = ', '.join(f'{f}: {c}颗' for f, c in entries)
                warnings.append({
                    'level': 'warning',
                    'type': '芯片数不一致',
                    'detail': f'{tt}各轮次芯片数不同: {detail}。可能R1/R2只复测了fail芯片'
                })

        # 3. chip_id 跨轮次缺失检测
        all_ids_per_type = defaultdict(set)
        for f, info in file_info.items():
            if info['test_type']:
                all_ids_per_type[info['test_type']] |= info['chip_ids']

        for tt, all_ids in all_ids_per_type.items():
            for f, info in file_info.items():
                if info['test_type'] != tt:
                    continue
                missing = all_ids - info['chip_ids']
                # 只报告少量缺失（大量缺失是正常的——R1/R2 可能只复测 fail 芯片）
                if 0 < len(missing) <= 10:
                    warnings.append({
                        'level': 'info',
                        'type': 'chip_id缺失轮次',
                        'detail': f'{f}: {len(missing)}颗芯片未出现: {", ".join(sorted(list(missing))[:5])}'
                    })

        # 4. 测试项数量变化（test program 变更）
        type_test_items = defaultdict(list)
        for f, info in file_info.items():
            if info['test_type']:
                type_test_items[info['test_type']].append((f, info['test_items']))

        for tt, entries in type_test_items.items():
            counts = [c for _, c in entries]
            if len(set(counts)) > 1:
                detail = ', '.join(f'{f}: {c}项' for f, c in entries)
                warnings.append({
                    'level': 'warning',
                    'type': '测试项数量变化',
                    'detail': f'{tt}各轮次测试项数量不同: {detail}。可能是test program变更'
                })

        # 5. 异常值检测（-999、-9999 等常见哨兵值）
        for f, info in file_info.items():
            if not isinstance(info['chip_ids'], set):
                continue
            struct = parser._parse_csv_structure(f)
            if 'error' in struct:
                continue
            data = struct['data']
            test_items = struct['test_items']
            data_head_row = struct['data_head_row']
            sentinel_items = []
            for item in test_items:
                try:
                    low = float(item['low'])
                    high = float(item['high'])
                except (ValueError, TypeError):
                    continue
                if low > high:
                    continue
                # 检查是否有极端负值（-999, -9999 等哨兵值）
                for rr in range(data_head_row + 1, min(data_head_row + 20, struct['rows'])):
                    val_str = data.get((rr, item['col']), '')
                    if not val_str or val_str == 'nan':
                        continue
                    try:
                        val = float(val_str)
                        if val < -100 and (low - val) > (high - low) * 10:
                            sentinel_items.append(item['short_name'])
                            break
                    except ValueError:
                        continue
            if sentinel_items:
                warnings.append({
                    'level': 'warning',
                    'type': '异常哨兵值',
                    'detail': f'{f}: {len(sentinel_items)}个测试项可能含-999等哨兵值: {", ".join(sentinel_items[:5])}'
                })

        return {
            'warnings': warnings,
            'warning_count': len(warnings),
            'files_checked': len(file_info),
            'summary': f'检查{len(file_info)}个文件，发现{len(warnings)}个问题'
                       + ('，数据完整性良好' if not warnings else '')
        }


class GenerateCharts:
    """生成分析图表"""
    description = "生成分析图表：Fail项柱状图、良率饼图、良率趋势折线图。保存为PNG文件，返回文件路径供报告引用。无需参数。"
    _persistent_fails_data = None  # 由 Agent 在调用前设置，避免重复计算

    def execute(self):
        log.info("GenerateCharts 执行")
        charts = parser.generate_charts(persistent_fails_data=self._persistent_fails_data)
        return {
            'charts': charts,
            'summary': f'已生成{len(charts)}张图表。在最终报告中用 ![图表名](路径) 引用这些图片。'
        }
