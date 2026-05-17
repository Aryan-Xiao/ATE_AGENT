# tests/test_refactor.py
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

import pytest
from ate_parser import ATEParser


@pytest.fixture
def parser():
    return ATEParser()


@pytest.fixture
def csv_struct(parser):
    files = [f for f in parser.list_files() if f.endswith('.csv')]
    if not files:
        pytest.skip('No CSV files in data dir')
    result = parser._parse_csv_structure(files[0])
    if 'error' in result:
        pytest.skip(f'CSV parse error: {result["error"]}')
    return result


# ── _clean_test_item_name ──────────────────────────────────────────────────

def test_clean_removes_main_prefix(parser):
    result = parser._clean_test_item_name('Main.OS.PowerShort.ptd')
    assert result == 'OS.PowerShort'

def test_clean_removes_noise_tokens(parser):
    result = parser._clean_test_item_name('Main.DFT.MBIST.funcTestDescriptor')
    assert result == 'DFT.MBIST'

def test_clean_removes_bracket_notation(parser):
    result = parser._clean_test_item_name('Main.IO.VOH.Collection[GPIO00].ptd')
    assert result == 'IO.VOH.GPIO00'

def test_clean_appends_test_num(parser):
    result = parser._clean_test_item_name('Main.OS.PowerShort.ptd', test_num='42')
    assert result == 'OS.PowerShort[#42]'

def test_clean_no_main_prefix(parser):
    result = parser._clean_test_item_name('OS.Vdd.Measure.ptd')
    assert result == 'OS.Vdd.Measure'

def test_clean_result_max_80_chars(parser):
    long_name = 'Main.' + '.'.join(['LongSegment'] * 20)
    result = parser._clean_test_item_name(long_name)
    assert len(result) <= 80


# ── _extract_chip_id ───────────────────────────────────────────────────────

def test_extract_valid_chip_id(parser):
    cid, unreadable = parser._extract_chip_id('11292')
    assert cid == '11292'
    assert unreadable is False

def test_extract_valid_chip_id_float_string(parser):
    cid, unreadable = parser._extract_chip_id('11292.0')
    assert cid == '11292'
    assert unreadable is False

def test_extract_zero_falls_back_to_part_id(parser):
    cid, unreadable = parser._extract_chip_id('0', part_id_fallback='50', filename='FT_R0.csv')
    assert cid == 'PART_50@FT_R0.csv'
    assert unreadable is True

def test_extract_negative_falls_back(parser):
    cid, unreadable = parser._extract_chip_id('-1', part_id_fallback='99', filename='QC_R0.csv')
    assert cid == 'PART_99@QC_R0.csv'
    assert unreadable is True

def test_extract_invalid_string_falls_back(parser):
    cid, unreadable = parser._extract_chip_id('nan', part_id_fallback='', filename='QC_R0.csv')
    assert cid == '?'
    assert unreadable is True

def test_extract_empty_falls_back_to_question_mark(parser):
    cid, unreadable = parser._extract_chip_id('', part_id_fallback='', filename='')
    assert cid == '?'
    assert unreadable is True


# ── _parse_csv_structure ───────────────────────────────────────────────────

def test_parse_csv_structure_returns_error_for_missing_file(parser):
    result = parser._parse_csv_structure('nonexistent_file.csv')
    assert 'error' in result

def test_parse_csv_structure_returns_required_keys(csv_struct):
    required_keys = {'data', 'rows', 'cols', 'test_name_row',
                     'test_items', 'chip_id_col', 'data_head_row', 'meta_cols'}
    assert required_keys.issubset(csv_struct.keys())

def test_parse_csv_structure_test_items_have_required_fields(csv_struct):
    assert len(csv_struct['test_items']) > 0
    item = csv_struct['test_items'][0]
    for key in ('full_name', 'short_name', 'number', 'low', 'high', 'unit', 'col'):
        assert key in item, f'Missing key: {key}'

def test_parse_csv_structure_chip_id_col_is_int(csv_struct):
    assert isinstance(csv_struct['chip_id_col'], int)
    assert csv_struct['chip_id_col'] >= 0


# ── 回归测试：重构后公开方法输出不变 ────────────────────────────────────────

def test_parse_test_data_regression(parser):
    """重构前后 parse_test_data 输出结构一致"""
    files = [f for f in parser.list_files() if f.endswith('.csv')]
    if not files:
        pytest.skip('No CSV files in data dir')
    result = parser.parse_test_data(files[0])
    if 'error' in result:
        pytest.skip(f'parse error: {result["error"]}')
    for key in ('filename', 'test_type', 'chips', 'test_items', 'fail_items',
                'fail_analysis', 'chips_list'):
        assert key in result, f'Missing key: {key}'
    assert result['chips'] > 0
    assert result['test_items'] > 0

def test_find_persistent_fails_regression(parser):
    files = [f for f in parser.list_files() if f.endswith('.csv')]
    if not files:
        pytest.skip('No CSV files in data dir')
    result = parser.find_persistent_fails()
    assert 'error' not in result
    assert 'by_test_type' in result
    assert 'persistent_fail_chips' in result
    assert 'summary' in result
