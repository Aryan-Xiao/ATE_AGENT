"""
ATE数据解析器 v5 —— 最终版本

数据格式确认：
  summary.xlsx  → Bin汇总（ALL_IN/PASS/FAIL + Bin明细）
  CSV文件       → 转置宽表（Test Name行 + 数据行）
  
每个CSV包含完整测试记录：测试项定义(910列) + N颗芯片数据
"""

import pandas as pd
import os
import re

ATE_DATA_DIR = os.getenv("ATE_DATA_DIR", 
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))


class ATEParser:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir or ATE_DATA_DIR

    def _find_chip_id_col(self, data, rows, test_name_row, data_head_row):
        """找到唯一值最多的 chip_id 列作为芯片硅ID

        chip_id_0_h 通常是批次/产品ID（所有行值相同），chip_id_1_l 才是真正的芯片硅ID。
        因此在多个含 chip_id 的列中，选择唯一非零值最多的那个。
        """
        candidates = []
        for c in range(1, max(data.keys(), key=lambda k: k[1])[1] + 1):
            name = data.get((test_name_row, c), '')
            name_lower = name.lower()
            if 'chip_id' in name_lower and 'flag' not in name_lower and 'bitmap' not in name_lower:
                candidates.append(c)

        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]

        best_col = candidates[0]
        best_unique = 0
        for c in candidates:
            vals = set()
            for r in range(data_head_row + 1, rows):
                v = data.get((r, c), '')
                if v and v != 'nan':
                    try:
                        iv = int(float(v))
                        if iv != 0:
                            vals.add(v)
                    except (ValueError, TypeError):
                        vals.add(v)
            if len(vals) > best_unique:
                best_unique = len(vals)
                best_col = c
        return best_col

    def _clean_test_item_name(self, name: str, test_num: str = '') -> str:
        """清理测试项全名，生成可区分的短名称（最长80字符）"""
        name_clean = name.replace('[', '.').replace(']', '').replace('.signalGroup', '')
        parts = name_clean.split('.')
        if parts and parts[0] == 'Main':
            parts = parts[1:]
        noise_tokens = ('Collection', 'funcTestDescriptor', 'Read_LBID', 'Read_deviceID', 'ptdGroup')
        filtered = [p for p in parts if p not in noise_tokens]
        if filtered and filtered[-1] in ('ptd', 'ftd'):
            filtered = filtered[:-1]
        if filtered:
            short = '.'.join(filtered)
        elif len(parts) >= 3:
            short = '.'.join(parts[-3:])
        else:
            short = name_clean[-80:]
        if test_num and test_num != 'nan':
            short = f"{short}[#{test_num}]"
        return short[:80]

    def _extract_chip_id(self, chip_id_raw: str, part_id_fallback: str = '', filename: str = '') -> tuple:
        """从原始单元格值提取有效 chip_id。

        返回 (chip_id_str, is_unreadable)：
          is_unreadable=False  → 有效正整数，chip_id_str 为其字符串
          is_unreadable=True   → 无效/零/负值，chip_id_str 为回退标识
        """
        try:
            cid_int = int(float(chip_id_raw))
            if cid_int > 0:
                return str(cid_int), False
            fallback = f'PART_{part_id_fallback}@{filename}' if part_id_fallback else '?'
            return fallback, True
        except (ValueError, TypeError):
            fallback = f'PART_{part_id_fallback}@{filename}' if part_id_fallback else '?'
            return fallback, True

    def list_files(self):
        return sorted([f for f in os.listdir(self.data_dir)
                        if f.endswith(('.csv', '.xlsx', '.xls'))])

    def _parse_file_meta(self, filename):
        """从文件名提取测试类型(FT/QC)和轮次(R0/R1/R2)"""
        fname = os.path.splitext(filename)[0]
        m = re.search(r'(FT|QC)[_-]?(R\d+)', fname, re.IGNORECASE)
        if m:
            test_type = m.group(1).upper()
            round_name = m.group(2).upper()
            round_index = int(round_name[1:])
            return {'test_type': test_type, 'round': round_name, 'round_index': round_index}
        return {'test_type': None, 'round': None, 'round_index': None}
    
    # ═══ Summary ═══
    
    def parse_summary(self, filename="summary.xlsx"):
        xls = pd.ExcelFile(os.path.join(self.data_dir, filename))
        rounds = {}

        for sheet_name in xls.sheet_names:
            df = pd.read_excel(xls, sheet_name=sheet_name, header=None)

            # 从 Row 1 识别轮次列位置：[4]=FT_R0, [6]=QC_R1 等
            round_cols = {}
            if len(df) > 1:
                for c in range(4, len(df.columns)):
                    v = str(df.iloc[1, c]).strip() if not pd.isna(df.iloc[1, c]) else ''
                    if v and v not in ('CNT', 'Yield', 'SBIN', 'nan'):
                        round_cols[v] = c  # round_name -> CNT 所在列

            # 每个 CNT 列后面是 Yield 列
            for round_name, cnt_col in round_cols.items():
                total, pass_cnt, fail_cnt = 0, 0, 0
                bins = []
                in_detail = False

                for i in range(len(df)):
                    c1 = str(df.iloc[i, 1]).strip() if not pd.isna(df.iloc[i, 1]) else ''
                    c2 = str(df.iloc[i, 2]).strip() if not pd.isna(df.iloc[i, 2]) else ''
                    c3 = str(df.iloc[i, 3]).strip() if not pd.isna(df.iloc[i, 3]) else ''
                    cnt_val = str(df.iloc[i, cnt_col]).strip() if cnt_col < len(df.columns) and not pd.isna(df.iloc[i, cnt_col]) else ''

                    if c1 == 'SBIN':
                        in_detail = True
                        continue

                    # ALL_IN/PASS/FAIL
                    if c2 == 'ALL_IN':
                        try: total = int(float(cnt_val))
                        except: pass
                        continue
                    elif c2 == 'PASS':
                        try: pass_cnt = int(float(cnt_val))
                        except: pass
                        continue
                    elif c2 == 'FAIL':
                        try: fail_cnt = int(float(cnt_val))
                        except: pass
                        continue

                    if in_detail:
                        if not c1:
                            continue
                        try:
                            cnt = int(float(cnt_val))
                        except:
                            cnt = 0
                        if cnt > 0:
                            result = c3.upper() if c3 else ('PASS' if c1 == '1' else 'FAIL')
                            bins.append({'sbin': c1, 'bin_name': c2, 'result': result, 'count': cnt})

                rounds[round_name] = {
                    'total': total, 'pass': pass_cnt, 'fail': fail_cnt,
                    'yield': f'{pass_cnt/total*100:.1f}%' if total > 0 else 'N/A',
                    'bins': bins
                }

        # 兼容旧接口：返回整体汇总（取第一个 round 或合并）
        first_round = next(iter(rounds.values()), {'total': 0, 'pass': 0, 'fail': 0, 'yield': 'N/A', 'bins': []})
        return {
            'total': first_round['total'],
            'pass': first_round['pass'],
            'fail': first_round['fail'],
            'yield': first_round['yield'],
            'bins': first_round['bins'],
            'rounds': rounds
        }
    
    # ═══ CSV解析 ═══
    
    def _read_csv(self, filename):
        path = os.path.join(self.data_dir, filename)
        with open(path, 'r') as f:
            lines = [line.strip() for line in f if line.strip()]
        
        max_cols = max(len(line.split(',')) for line in lines)
        data = {}
        for r, line in enumerate(lines):
            parts = line.split(',')
            for c, val in enumerate(parts):
                data[(r, c)] = val.strip()
        return data, len(lines), max_cols

    def _parse_csv_structure(self, filename: str) -> dict:
        """解析 CSV 文件的固定结构部分（Test Name 行、测试项、数据头行、chip_id 列、meta_cols）。

        成功返回包含以下键的 dict：
            data, rows, cols, test_name_row, test_items,
            chip_id_col, data_head_row, meta_cols
        失败返回 {'error': '原因'}
        """
        try:
            data, rows, cols = self._read_csv(filename)
        except Exception as e:
            return {'error': f'读取文件失败: {e}'}

        # 找 Test Name 行
        test_name_row = None
        for r in range(min(5, rows)):
            first_val = data.get((r, 0), '').lower()
            row1_val = data.get((r, 1), '').lower()
            if 'test name' in first_val or 'test name' in row1_val:
                test_name_row = r
                break
        if test_name_row is None:
            return {'error': '找不到Test Name行'}

        # 提取测试项，同时收集 chip_id 候选列
        test_items = []
        chip_id_candidates = []
        for c in range(1, cols):
            name = data.get((test_name_row, c), '')
            if not name or name == 'nan':
                continue
            test_num = data.get((test_name_row + 1, c), '')
            short = self._clean_test_item_name(name, test_num)
            test_items.append({
                'full_name': name[:120],
                'short_name': short,
                'number': test_num,
                'low': data.get((test_name_row + 2, c), ''),
                'high': data.get((test_name_row + 3, c), ''),
                'unit': data.get((test_name_row + 4, c), ''),
                'col': c
            })
            name_lower = name.lower()
            if 'chip_id' in name_lower and 'flag' not in name_lower and 'bitmap' not in name_lower:
                chip_id_candidates.append(c)

        if not chip_id_candidates:
            return {'error': '找不到chip_id测试项（模糊匹配含chip_id且不含flag/bitmap的列）'}

        # 找数据头行
        data_head_row = test_name_row + 5
        while data_head_row < rows:
            v = data.get((data_head_row, 0), '').lower()
            if v in ['id', 'lid', 'filename', 'starttime', 'lot_id', '']:
                break
            data_head_row += 1

        if data_head_row >= rows:
            return {'error': '找不到数据头行'}

        # 选最优 chip_id 列
        chip_id_col = self._find_chip_id_col(data, rows, test_name_row, data_head_row)
        if chip_id_col is None:
            return {'error': '找不到有效的chip_id列（所有chip_id列值都相同或为0）'}

        # 解析 meta_cols
        meta_cols = {}
        for c in range(min(15, cols)):
            h = data.get((data_head_row, c), '')
            if h and h != 'nan':
                meta_cols[c] = h

        return {
            'data': data,
            'rows': rows,
            'cols': cols,
            'test_name_row': test_name_row,
            'test_items': test_items,
            'chip_id_col': chip_id_col,
            'data_head_row': data_head_row,
            'meta_cols': meta_cols,
        }

    def parse_test_data(self, filename):
        struct = self._parse_csv_structure(filename)
        if 'error' in struct:
            return struct

        data = struct['data']
        rows = struct['rows']
        cols = struct['cols']
        test_items = struct['test_items']
        chip_id_col = struct['chip_id_col']
        data_head_row = struct['data_head_row']
        meta_cols = struct['meta_cols']

        # 解析芯片
        chips = []
        for r in range(data_head_row + 1, rows):
            vals = [data.get((r, c), '') for c in range(min(8, cols))]
            if all(v == '' or v == 'nan' for v in vals):
                continue

            chip = {'test_values': {}}
            for c, header in meta_cols.items():
                val = data.get((r, c), '')
                if val and val != 'nan':
                    chip[header] = val

            for item in test_items:
                val = data.get((r, item['col']), '')
                if val and val != 'nan':
                    try:
                        chip['test_values'][item['short_name']] = float(val)
                    except (ValueError, TypeError):
                        chip['test_values'][item['short_name']] = val

            part_id = chip.get('PART_ID', '')
            chip_id_raw = data.get((r, chip_id_col), '')
            chip_id_str, unreadable = self._extract_chip_id(chip_id_raw, part_id, filename)
            chip['chip_id'] = chip_id_str
            if unreadable:
                chip['chip_id_unreadable'] = True

            chips.append(chip)

        # 去重：同一 chip_id 可能被测量多次（同一文件中），取最后一次测量为最终结果
        seen = {}
        duplicates_info = {}
        for i, chip in enumerate(chips):
            cid = chip.get('chip_id', '?')
            if cid in seen:
                if cid not in duplicates_info:
                    duplicates_info[cid] = {'measurement_count': 1, 'first_row_part_id': chips[seen[cid]].get('PART_ID', '')}
                duplicates_info[cid]['measurement_count'] += 1
                duplicates_info[cid]['last_row_part_id'] = chip.get('PART_ID', '')
            seen[cid] = i

        # 保留最后一次测量（seen中存的是最后出现的索引，因为后面的覆盖前面的）
        # 重新构建：最后一个同名 chip 覆盖前面的
        final_chips = {}
        for chip in chips:
            cid = chip.get('chip_id', '?')
            final_chips[cid] = chip

        if duplicates_info:
            for cid, info in duplicates_info.items():
                if cid in final_chips:
                    final_chips[cid]['duplicate_measurements'] = info['measurement_count']

        chips = list(final_chips.values())
        
        # Fail分析
        fail_analysis = []
        for item in test_items:
            try:
                low = float(item['low'])
                high = float(item['high'])
            except:
                continue
            
            fail_chips = []
            for chip in chips:
                val = chip['test_values'].get(item['short_name'])
                if isinstance(val, (int, float)) and (val < low or val > high):
                    fail_chips.append({
                        'chip_id': chip.get('chip_id', '?'),
                        'value': val
                    })
            
            if fail_chips:
                fail_analysis.append({
                    'test_item': item['short_name'],
                    'spec': f"{item['low']}~{item['high']}{item['unit']}",
                    'fail_count': len(fail_chips),
                    'fail_rate': f'{len(fail_chips)/len(chips)*100:.1f}%' if chips else '0%',
                    'fail_chips_sample': fail_chips[:5]
                })
        
        fail_analysis.sort(key=lambda x: x['fail_count'], reverse=True)

        file_meta = self._parse_file_meta(filename)
        test_type = file_meta['test_type'] or filename.replace('.csv', '').split('_')[-1]

        return {
            'filename': filename,
            'test_type': test_type,
            'round': file_meta['round'],
            'round_index': file_meta['round_index'],
            'chips': len(chips),
            'test_items': len(test_items),
            'fail_items': len(fail_analysis),
            'fail_analysis': fail_analysis,
            'chips_list': chips
        }
    
    # ═══ 跨轮次追踪 ═══

    def get_chip_results(self, chip_id):
        """追踪单颗芯片在所有轮次中的测试结果

        参数:
            chip_id: 芯片硅ID (chip_id测试项的值，字符串或整数)

        返回:
            dict: {chip_id, rounds: [{filename, round, hard_bin, soft_bin, pass_fail, fail_items: [...]}]}
        """
        chip_id_str = str(chip_id)
        files = [f for f in self.list_files() if f.endswith('.csv')]
        rounds = []

        for f in files:
            struct = self._parse_csv_structure(f)
            if 'error' in struct:
                continue
            data = struct['data']
            rows = struct['rows']
            cols = struct['cols']
            test_items = struct['test_items']
            chip_id_col = struct['chip_id_col']
            data_head_row = struct['data_head_row']
            meta_cols = struct['meta_cols']

            # 通过 chip_id 测试项列查找目标芯片（取最后一次测量）
            last_match = None
            match_count = 0
            for r in range(data_head_row + 1, rows):
                vals = [data.get((r, c), '') for c in range(min(8, cols))]
                if all(v == '' or v == 'nan' for v in vals):
                    continue

                chip_id_val_raw = data.get((r, chip_id_col), '')
                effective_id, _ = self._extract_chip_id(chip_id_val_raw)

                if str(effective_id) != chip_id_str:
                    continue

                match_count += 1

                # 记录这行的信息（后面的覆盖前面的）
                chip_meta = {}
                for c, header in meta_cols.items():
                    val = data.get((r, c), '')
                    if val and val != 'nan':
                        chip_meta[header] = val

                fail_items = []
                for item in test_items:
                    val_str = data.get((r, item['col']), '')
                    if not val_str or val_str == 'nan':
                        continue
                    try:
                        val = float(val_str)
                        low = float(item['low'])
                        high = float(item['high'])
                        if val < low or val > high:
                            fail_items.append({
                                'test_item': item['short_name'],
                                'value': val,
                                'spec': f"{item['low']}~{item['high']}"
                            })
                    except ValueError:
                        continue

                file_meta = self._parse_file_meta(f)
                last_match = {
                    'filename': f,
                    'test_type': file_meta['test_type'],
                    'round': file_meta['round'] or '?',
                    'round_index': file_meta['round_index'],
                    'hard_bin': chip_meta.get('HARD_BIN', '?'),
                    'soft_bin': chip_meta.get('SOFT_BIN', '?'),
                    'pass_fail': chip_meta.get('PART_FLG', '?'),
                    'fail_count': len(fail_items),
                    'fail_items': fail_items
                }

            if last_match:
                if match_count > 1:
                    last_match['duplicate_measurements'] = match_count
                rounds.append(last_match)

        # 汇总: 该芯片在哪些轮次fail，哪些测试项持续fail
        all_fail_items = {}
        for rd in rounds:
            for fi in rd['fail_items']:
                key = fi['test_item']
                if key not in all_fail_items:
                    all_fail_items[key] = []
                all_fail_items[key].append(rd['round'])

        persistent_fails = [
            {'test_item': k, 'fail_rounds': v, 'fail_count': len(v)}
            for k, v in all_fail_items.items() if len(v) >= 2
        ]
        persistent_fails.sort(key=lambda x: x['fail_count'], reverse=True)

        # 按 test_type 分组
        rounds_by_type = {}
        for rd in rounds:
            tt = rd.get('test_type')
            if tt:
                if tt not in rounds_by_type:
                    rounds_by_type[tt] = []
                rounds_by_type[tt].append(rd)

        persistent_by_type = {}
        for rd in rounds:
            tt = rd.get('test_type')
            for fi in rd['fail_items']:
                key = fi['test_item']
                if tt not in persistent_by_type:
                    persistent_by_type[tt] = {}
                if key not in persistent_by_type[tt]:
                    persistent_by_type[tt][key] = []
                persistent_by_type[tt][key].append(rd['round'])

        persistent_by_type_list = {}
        for tt, items in persistent_by_type.items():
            persistent_by_type_list[tt] = [
                {'test_item': k, 'fail_rounds': v, 'fail_count': len(v)}
                for k, v in items.items() if len(v) >= 2
            ]
            persistent_by_type_list[tt].sort(key=lambda x: x['fail_count'], reverse=True)

        return {
            'chip_id': chip_id_str,
            'total_rounds_tested': len(rounds),
            'rounds': rounds,
            'rounds_by_type': rounds_by_type,
            'persistent_fails': persistent_fails,
            'persistent_fails_by_type': persistent_by_type_list,
            'summary': f"芯片#{chip_id_str}在{len(rounds)}个轮次中测试"
                       + (f"，{len(persistent_fails)}个测试项在≥2轮中持续fail" if persistent_fails else "，无持续fail项")
        }

    def compute_final_status(self, chip_id):
        """计算单颗芯片在 FT/QC 各自的最终状态

        状态定义：
          PASS        - 初测(R0)即通过
          RETEST_PASS - R0 fail 但 R1/R2 中有 pass（稳定性不确定）
          FAIL        - 所有轮次都 fail
        """
        chip_result = self.get_chip_results(chip_id)
        status = {'chip_id': str(chip_id)}

        rounds_by_type = chip_result.get('rounds_by_type', {})

        for tt, rounds in rounds_by_type.items():
            rounds_sorted = sorted(rounds, key=lambda r: r.get('round_index') if isinstance(r.get('round_index'), int) else 0)

            round_details = []
            has_pass = False
            has_r0_pass = False
            r0_fail_items = []

            for rd in rounds_sorted:
                pf = rd.get('pass_fail', '').upper()
                # PART_FLG 可能是 'P'/'F' 或 'PASS'/'FAIL'
                is_pass = pf in ('P', 'PASS') if pf else (rd.get('fail_count', 0) == 0)
                ri = rd.get('round_index', 0)
                round_details.append(f"R{ri}→{'PASS' if is_pass else 'FAIL'}")
                if is_pass:
                    has_pass = True
                    if ri == 0:
                        has_r0_pass = True
                else:
                    if ri == 0:
                        r0_fail_items = [fi['test_item'] for fi in rd.get('fail_items', [])]

            if has_r0_pass:
                s = 'PASS'
                uncertainty = None
            elif has_pass:
                s = 'RETEST_PASS'
                pass_round = 'R?'
                for rd in rounds_sorted:
                    pf = rd.get('pass_fail', '')
                    is_pass = 'PASS' in pf.upper() if pf else (rd.get('fail_count', 0) == 0)
                    if is_pass:
                        pass_round = f"R{rd.get('round_index', '?')}"
                        break
                max_ri = max((rd.get('round_index', 0) for rd in rounds_sorted if isinstance(rd.get('round_index'), int)), default=0)
                uncertainty = f"{pass_round}复测通过，但R{max_ri+1}及后续轮次未测试，稳定性不确定"
            else:
                s = 'FAIL'
                uncertainty = None

            status[tt] = {
                'status': s,
                'detail': ', '.join(round_details),
                'uncertainty': uncertainty,
                'fail_items_in_r0': r0_fail_items if s != 'PASS' else []
            }

        return status

    def find_persistent_fails(self, min_rounds=2):
        """找出在多个轮次中持续fail的芯片

        参数:
            min_rounds: 至少在几个轮次中fail才算"持续fail" (默认2)

        返回:
            dict: {persistent_chips: [...], persistent_test_items: [...], summary}
        """
        files = [f for f in self.list_files() if f.endswith('.csv')]
        if not files:
            return {'error': '没有找到CSV数据文件'}

        # 收集每个文件中每个芯片的fail信息
        # chip_fail_map: {chip_id: {test_item: [round1, round2, ...]}}
        chip_fail_map = {}
        chip_round_results = {}  # {chip_id: [{round, pass_fail, fail_count}]}

        for f in files:
            r = self.parse_test_data(f)
            if 'error' in r:
                continue

            # 从文件名提取轮次
            file_meta = self._parse_file_meta(f)
            test_type = file_meta['test_type']
            round_info = file_meta['round'] or '?'
            round_index = file_meta['round_index']

            # 重新解析获取每个芯片的chip_id和fail详情
            data, rows, cols = self._read_csv(f)

            test_name_row = None
            for rr in range(min(5, rows)):
                first_val = data.get((rr, 0), '').lower()
                row1_val = data.get((rr, 1), '').lower()
                if 'test name' in first_val or 'test name' in row1_val:
                    test_name_row = rr
                    break
            if test_name_row is None:
                continue

            test_items = []
            chip_id_candidates = []
            for c in range(1, cols):
                name = data.get((test_name_row, c), '')
                if not name or name == 'nan':
                    continue
                name_clean = name.replace('[', '.').replace(']', '').replace('.signalGroup', '')
                name_parts = name_clean.split('.')
                if name_parts and name_parts[0] == 'Main':
                    name_parts = name_parts[1:]
                noise_tokens = ('Collection', 'funcTestDescriptor', 'Read_LBID', 'Read_deviceID', 'ptdGroup')
                filtered = [p for p in name_parts if p not in noise_tokens]
                if filtered and filtered[-1] in ('ptd', 'ftd'):
                    filtered = filtered[:-1]
                short = '.'.join(filtered) if filtered else ('.'.join(name_parts[-3:]) if len(name_parts) >= 3 else name_clean[-80:])
                test_num = data.get((test_name_row + 1, c), '')
                if test_num and test_num != 'nan':
                    short = f"{short}[#{test_num}]"
                test_items.append({
                    'short_name': short[:80],
                    'low': data.get((test_name_row + 2, c), ''),
                    'high': data.get((test_name_row + 3, c), ''),
                    'col': c
                })

                name_lower = name.lower()
                if 'chip_id' in name_lower and 'flag' not in name_lower and 'bitmap' not in name_lower:
                    chip_id_candidates.append(c)

            data_head_row = test_name_row + 5
            while data_head_row < rows:
                v = data.get((data_head_row, 0), '').lower()
                if v in ['id', 'lid', 'filename', 'starttime', 'lot_id', '']:
                    break
                data_head_row += 1

            if not chip_id_candidates:
                continue
            chip_id_col = self._find_chip_id_col(data, rows, test_name_row, data_head_row)
            if chip_id_col is None:
                continue

            meta_cols = {}
            for c in range(min(15, cols)):
                h = data.get((data_head_row, c), '')
                if h and h != 'nan':
                    meta_cols[c] = h

            for rr in range(data_head_row + 1, rows):
                vals = [data.get((rr, c), '') for c in range(min(8, cols))]
                if all(v == '' or v == 'nan' for v in vals):
                    continue

                chip_id = data.get((rr, chip_id_col), '?')
                try:
                    cid_int = int(float(chip_id))
                    if cid_int > 0:
                        chip_id = str(cid_int)
                    else:
                        # ID 读取失败，用 PART_ID 做回退（但无法跨文件追踪）
                        part_id_val = data.get((rr, 6), '')  # PART_ID 通常在 col 6
                        chip_id = f'PART_{part_id_val}@{f}' if part_id_val else None
                        if chip_id is None:
                            continue
                except (ValueError, TypeError):
                    part_id_val = data.get((rr, 6), '')
                    chip_id = f'PART_{part_id_val}@{f}' if part_id_val else None
                    if chip_id is None:
                        continue

                part_flg = ''
                for c, h in meta_cols.items():
                    if h == 'PART_FLG':
                        part_flg = data.get((rr, c), '')
                        break

                # 检查这颗芯片的fail项
                chip_fails_this_round = []
                for item in test_items:
                    val_str = data.get((rr, item['col']), '')
                    if not val_str or val_str == 'nan':
                        continue
                    try:
                        val = float(val_str)
                        low = float(item['low'])
                        high = float(item['high'])
                        if val < low or val > high:
                            chip_fails_this_round.append(item['short_name'])
                    except ValueError:
                        continue

                # 累积到chip_fail_map（按 test_type+round 去重）
                if chip_id not in chip_fail_map:
                    chip_fail_map[chip_id] = {}
                    chip_round_results[chip_id] = []
                for test_item in chip_fails_this_round:
                    if test_item not in chip_fail_map[chip_id]:
                        chip_fail_map[chip_id][test_item] = []
                    # 去重：同一个 test_type + round 不重复记录
                    existing_keys = {(r['test_type'], r['round']) for r in chip_fail_map[chip_id][test_item]}
                    if (test_type, round_info) not in existing_keys:
                        chip_fail_map[chip_id][test_item].append({
                            'test_type': test_type,
                            'round': round_info,
                            'round_index': round_index
                        })

                # 去重：同一 test_type + round 不重复记录 chip_round_results
                existing_rr_keys = {(r['test_type'], r['round']) for r in chip_round_results[chip_id]}
                if (test_type, round_info) not in existing_rr_keys:
                    chip_round_results[chip_id].append({
                        'test_type': test_type,
                        'round': round_info,
                        'round_index': round_index,
                        'pass_fail': part_flg,
                        'fail_count': len(chip_fails_this_round)
                    })

        # 按测试类型(FT/QC)分组判定持续fail
        by_test_type = {}
        for tt in ('FT', 'QC'):
            # 收集该类型的轮次列表
            tt_rounds_analyzed = sorted(set(
                r['round'] for r_list in chip_round_results.values()
                for r in r_list if r.get('test_type') == tt
            ))
            if not tt_rounds_analyzed:
                continue

            tt_chips = {}
            for chip_id, fail_items in chip_fail_map.items():
                tt_fail_items = {}
                for test_item, round_list in fail_items.items():
                    tt_rounds = [r for r in round_list if r.get('test_type') == tt]
                    if len(tt_rounds) >= min_rounds:
                        tt_fail_items[test_item] = tt_rounds
                if tt_fail_items:
                    tt_chips[chip_id] = tt_fail_items

            persistent_chips = []
            for chip_id, fail_items in tt_chips.items():
                persistent_items = []
                for test_item, fail_rounds in fail_items.items():
                    persistent_items.append({
                        'test_item': test_item,
                        'fail_rounds': [r['round'] for r in fail_rounds],
                        'fail_round_count': len(fail_rounds)
                    })
                persistent_items.sort(key=lambda x: x['fail_round_count'], reverse=True)
                tt_chip_rounds = [r for r in chip_round_results.get(chip_id, []) if r.get('test_type') == tt]
                persistent_chips.append({
                    'chip_id': chip_id,
                    'persistent_fail_items': persistent_items,
                    'total_rounds_tested': len(tt_chip_rounds),
                    'round_results': tt_chip_rounds
                })

            persistent_chips.sort(key=lambda x: len(x['persistent_fail_items']), reverse=True)

            item_chip_map = {}
            for pc in persistent_chips:
                for pi in pc['persistent_fail_items']:
                    key = pi['test_item']
                    if key not in item_chip_map:
                        item_chip_map[key] = []
                    item_chip_map[key].append({
                        'chip_id': pc['chip_id'],
                        'fail_rounds': pi['fail_rounds']
                    })

            # 单轮次时，R0 fail 即为最终结果，也需列出
            single_round = len(tt_rounds_analyzed) == 1
            if single_round:
                # 收集该类型 R0 中所有 fail 芯片（不限 min_rounds）
                r0_fail_chips = []
                r0_fail_item_map = {}
                for chip_id, fail_items in chip_fail_map.items():
                    tt_fails = []
                    for test_item, round_list in fail_items.items():
                        tt_rounds = [r for r in round_list if r.get('test_type') == tt]
                        if tt_rounds:
                            tt_fails.append({
                                'test_item': test_item,
                                'fail_rounds': [r['round'] for r in tt_rounds],
                                'fail_round_count': len(tt_rounds)
                            })
                    if tt_fails:
                        tt_chip_rounds = [r for r in chip_round_results.get(chip_id, []) if r.get('test_type') == tt]
                        r0_fail_chips.append({
                            'chip_id': chip_id,
                            'fail_items': tt_fails,
                            'total_rounds_tested': len(tt_chip_rounds),
                            'round_results': tt_chip_rounds
                        })
                        for fi in tt_fails:
                            if fi['test_item'] not in r0_fail_item_map:
                                r0_fail_item_map[fi['test_item']] = []
                            r0_fail_item_map[fi['test_item']].append(chip_id)

                r0_fail_test_items = [
                    {
                        'test_item': k,
                        'affected_chips': len(v),
                        'chip_ids': v[:10]
                    }
                    for k, v in sorted(r0_fail_item_map.items(), key=lambda x: len(x[1]), reverse=True)
                ]
            else:
                r0_fail_chips = []
                r0_fail_test_items = []

            by_test_type[tt] = {
                'rounds_analyzed': tt_rounds_analyzed,
                'single_round': single_round,
                'persistent_fail_chips': persistent_chips,
                'persistent_fail_count': len(persistent_chips),
                'persistent_test_items': [
                    {
                        'test_item': k,
                        'affected_chips': len(v),
                        'chip_details': v[:10]
                    }
                    for k, v in sorted(item_chip_map.items(), key=lambda x: len(x[1]), reverse=True)
                ],
                'r0_fail_chips': r0_fail_chips,
                'r0_fail_test_items': r0_fail_test_items,
                'r0_fail_chip_count': len(r0_fail_chips)
            }

        # 合并顶层兼容字段
        all_persistent_chips = []
        all_item_map = {}
        for tt, data in by_test_type.items():
            all_persistent_chips.extend(data['persistent_fail_chips'])
            for item in data['persistent_test_items']:
                if item['test_item'] not in all_item_map:
                    all_item_map[item['test_item']] = item
                else:
                    all_item_map[item['test_item']]['affected_chips'] += item['affected_chips']

        total_chips = len(chip_fail_map)
        tt_summaries = '; '.join(
            f"{tt}: {data['persistent_fail_count']}颗持续fail" for tt, data in by_test_type.items()
        )

        # 生成需关注清单：RETEST_PASS 且后续轮次无数据的芯片
        attention_list = []
        all_chip_ids = set(chip_fail_map.keys())
        # 也收集 pass 芯片（不在 chip_fail_map 中的）
        for chip_id in all_chip_ids:
            cs = self.compute_final_status(chip_id)
            for tt in ('FT', 'QC'):
                if tt in cs and cs[tt]['status'] == 'RETEST_PASS' and cs[tt].get('uncertainty'):
                    attention_list.append({
                        'chip_id': chip_id,
                        'test_type': tt,
                        'reason': cs[tt]['detail'] + '，但无后续轮次数据',
                        'failed_items_in_r0': cs[tt].get('fail_items_in_r0', []),
                        'passed_in_round': cs[tt]['detail'].split('→')[1].split(',')[0].strip() if '→' in cs[tt]['detail'] else '?'
                    })

        return {
            'by_test_type': by_test_type,
            'attention_list': attention_list,
            'total_chips_analyzed': total_chips,
            'min_rounds_threshold': min_rounds,
            'persistent_fail_chips': all_persistent_chips,
            'persistent_fail_count': len(all_persistent_chips),
            'persistent_test_items': list(all_item_map.values()),
            'summary': f"共{total_chips}颗芯片中，{tt_summaries}"
        }

    # ═══ 报告 ═══
    
    def full_report(self):
        files = self.list_files()
        
        print("╔══════════════════════════════════════════════╗")
        print("║     ATE 数据分析报告 — WQ7037AXB              ║")
        print("╚══════════════════════════════════════════════╝\n")
        
        s = self.parse_summary()
        print("📊 整体良率 (summary.xlsx)")
        print(f"   总计: {s['total']} | PASS: {s['pass']} | FAIL: {s['fail']}")
        print(f"   良率: {s['yield']}\n")
        print("   Fail Bin明细:")
        for b in s['bins']:
            if b['result'] == 'FAIL':
                print(f"     Bin {b['sbin']:5s} {b['bin_name']:20s} {b['count']:3d}颗")
        
        for f in files:
            if 'summary' in f.lower():
                continue
            
            r = self.parse_test_data(f)
            if 'error' in r:
                print(f"\n⚠️ {f}: {r['error']}")
                continue
            
            print(f"\n📄 {f} ({r['test_type']})")
            print(f"   芯片: {r['chips']}颗 | 测试项: {r['test_items']}个")
            
            if r['fail_analysis']:
                print(f"   FAIL测试项: {r['fail_items']}个 (共{r['test_items']}个中被检测到超限)")
                for fa in r['fail_analysis'][:8]:
                    chips_str = ', '.join(
                        f"chip#{c['chip_id']}={c['value']}" 
                        for c in fa['fail_chips_sample']
                    )
                    print(f"   ❌ {fa['test_item']:45s} [{fa['spec']}]  "
                          f"Fail:{fa['fail_count']}颗 ({fa['fail_rate']})  "
                          f"例:{chips_str}")
            else:
                print(f"   ✅ 所有测试项在规格内")
        
        print("\n" + "═" * 60)

    # ═══ 图表 ═══

    def generate_charts(self, output_dir=None):
        """生成分析图表：Fail项柱状图、良率饼图、良率趋势折线图

        返回: 生成的图表文件路径列表
        """
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        # 尝试中文字体，找不到则回退英文
        _cn_fonts = ['SimHei', 'WenQuanYi Micro Hei', 'Noto Sans CJK SC', 'Microsoft YaHei']
        _has_cn = False
        for f in _cn_fonts:
            try:
                from matplotlib.font_manager import FontManager
                fm = FontManager()
                if any(f.lower() in fn.name.lower() for fn in fm.ttflist):
                    plt.rcParams['font.sans-serif'] = [f, 'DejaVu Sans']
                    _has_cn = True
                    break
            except Exception:
                continue
        if not _has_cn:
            plt.rcParams['font.sans-serif'] = ['DejaVu Sans']
        plt.rcParams['axes.unicode_minus'] = False

        if output_dir is None:
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'reports')
        os.makedirs(output_dir, exist_ok=True)

        charts = []

        # 1. 各测试类型 TOP fail 项柱状图（标注各轮次样本量）
        pf = self.find_persistent_fails()
        # 收集各文件芯片数用于标注样本量
        file_chip_counts = {}
        for f in self.list_files():
            if f.endswith('.csv') and 'summary' not in f.lower():
                r = self.parse_test_data(f)
                file_chip_counts[f] = r.get('chips', 0)

        for tt, data in pf.get('by_test_type', {}).items():
            # 合并 persistent + r0_fail_test_items
            if data.get('single_round'):
                items = data.get('r0_fail_test_items', [])
            else:
                items = data.get('persistent_test_items', [])
            if not items:
                continue
            top_items = items[:15]
            names = [it['test_item'][:40] for it in top_items]
            counts = [it['affected_chips'] for it in top_items]

            fig, ax = plt.subplots(figsize=(12, 6))
            bars = ax.barh(range(len(names)), counts, color='#e74c3c', alpha=0.85)
            ax.set_yticks(range(len(names)))
            ax.set_yticklabels(names, fontsize=8)
            ax.invert_yaxis()
            ax.set_xlabel('Fail Chips' if not _has_cn else 'Fail芯片数', fontsize=10)

            # 标注各轮次样本量
            sample_info = []
            for rnd in data.get('rounds_analyzed', []):
                # 找到对应的文件
                for f, cnt in file_chip_counts.items():
                    meta = self._parse_file_meta(f)
                    if meta.get('test_type') == tt and meta.get('round') == rnd:
                        sample_info.append(f'{rnd}: {cnt}chips')
                        break
            sample_text = ' | '.join(sample_info)
            title = f'{tt} TOP Fail Items' if not _has_cn else f'{tt} TOP Fail测试项'
            if sample_text:
                title += f'\n({sample_text})'
            ax.set_title(title, fontsize=12, fontweight='bold')
            for bar, cnt in zip(bars, counts):
                ax.text(bar.get_width() + 0.3, bar.get_y() + bar.get_height()/2,
                        str(cnt), va='center', fontsize=8)
            plt.tight_layout()
            path = os.path.join(output_dir, f'{tt}_top_fails.png')
            plt.savefig(path, dpi=150)
            plt.close()
            charts.append(path)

        # 2. 各轮次良率饼图（跳过非标准轮次如"汇总"）
        summary = self.parse_summary()
        for round_name, rd in summary.get('rounds', {}).items():
            meta = self._parse_file_meta(round_name)
            if not meta.get('test_type'):
                continue
            fig, ax = plt.subplots(figsize=(5, 5))
            sizes = [rd['pass'], rd['fail']]
            labels = [f"PASS\n{rd['pass']}", f"FAIL\n{rd['fail']}"]
            colors = ['#2ecc71', '#e74c3c']
            explode = (0, 0.05)
            ax.pie(sizes, labels=labels, colors=colors, explode=explode,
                   autopct='%1.1f%%', startangle=90, textprops={'fontsize': 11})
            ax.set_title(f'{round_name} Yield (Total: {rd["total"]})' if not _has_cn else f'{round_name} 良率 (共{rd["total"]}颗)', fontsize=12, fontweight='bold')
            plt.tight_layout()
            path = os.path.join(output_dir, f'yield_pie_{round_name}.png')
            plt.savefig(path, dpi=150)
            plt.close()
            charts.append(path)

        # 3. FT/QC 各轮次良率趋势折线图
        rounds_by_type = {}
        for round_name, rd in summary.get('rounds', {}).items():
            meta = self._parse_file_meta(round_name)
            tt = meta.get('test_type')
            if tt:
                if tt not in rounds_by_type:
                    rounds_by_type[tt] = []
                yield_val = float(rd['yield'].replace('%', '')) if rd['yield'] != 'N/A' else 0
                rounds_by_type[tt].append({
                    'round': round_name,
                    'round_index': meta.get('round_index', 0),
                    'yield': yield_val,
                    'pass': rd['pass'],
                    'fail': rd['fail'],
                    'total': rd['total']
                })

        if rounds_by_type:
            fig, ax = plt.subplots(figsize=(8, 5))
            markers = {'FT': 'o', 'QC': 's'}
            colors_line = {'FT': '#3498db', 'QC': '#e67e22'}
            for tt, rounds in rounds_by_type.items():
                rounds_sorted = sorted(rounds, key=lambda x: x['round_index'])
                x_labels = [r['round'] for r in rounds_sorted]
                y_vals = [r['yield'] for r in rounds_sorted]
                ax.plot(x_labels, y_vals, marker=markers.get(tt, 'o'),
                        color=colors_line.get(tt, '#333'),
                        linewidth=2, markersize=8, label=tt)
                for xl, yv, rd in zip(x_labels, y_vals, rounds_sorted):
                    # 标注良率 + 样本量 (pass/total)
                    ax.annotate(f'{yv:.1f}%\n({rd["pass"]}/{rd["total"]})',
                                (xl, yv), textcoords="offset points",
                                xytext=(0, 12), ha='center', fontsize=8)
            ax.set_ylabel('Yield (%)' if not _has_cn else '良率 (%)', fontsize=10)
            title = 'FT/QC Yield Trend by Round'
            if _has_cn:
                title = 'FT/QC 各轮次良率趋势\n(R1/R2可能只复测之前fail的芯片)'
            ax.set_title(title, fontsize=12, fontweight='bold')
            ax.set_ylim(bottom=max(0, ax.get_ylim()[0] - 5), top=min(105, ax.get_ylim()[1] + 5))
            ax.legend(fontsize=10)
            ax.grid(True, alpha=0.3)
            plt.tight_layout()
            path = os.path.join(output_dir, 'yield_trend.png')
            plt.savefig(path, dpi=150)
            plt.close()
            charts.append(path)

        return charts


if __name__ == "__main__":
    ATEParser().full_report()
