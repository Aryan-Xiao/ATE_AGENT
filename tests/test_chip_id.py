"""测试 chip_id 迁移：模糊查找测试项中的 chip_id 作为芯片唯一标识"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ate_parser import ATEParser

parser = ATEParser()


def test_parse_test_data_chip_id_in_chips():
    """parse_test_data 应将 chip_id 测试项值提升为芯片元信息 chip['chip_id']"""
    r = parser.parse_test_data('WQ7037AXB_260508_QC_R0.csv')
    assert 'error' not in r, f"解析失败: {r.get('error')}"
    # 改造后：fail_chips_sample 中 chip_id 是 chip_id_1_l 的值（5位数硅ID），不是 PART_ID（1-215）
    if r['fail_analysis']:
        sample = r['fail_analysis'][0]['fail_chips_sample']
        if sample:
            cid = sample[0]['chip_id']
            assert cid, "chip_id 不应为空"
            assert cid != '?', "chip_id 不应为 '?'"


def test_parse_test_data_returns_chips_list():
    """parse_test_data 应返回 chips_list，每颗芯片包含 chip_id 元信息"""
    r = parser.parse_test_data('WQ7037AXB_260508_QC_R0.csv')
    assert 'chips_list' in r, "parse_test_data 应返回 chips_list"
    chips = r['chips_list']
    assert len(chips) > 0
    first_chip = chips[0]
    assert 'chip_id' in first_chip, "每颗芯片应有 chip_id 元信息"
    # chip_id 应来自 chip_id_1_l 测试项，不是 PART_ID
    assert first_chip['chip_id'] != first_chip.get('PART_ID', ''), \
        "chip_id 不应等于 PART_ID"


def test_chip_id_fuzzy_match():
    """模糊查找 chip_id 测试项：含 chip_id，排除 flag/bitmap"""
    r = parser.parse_test_data('WQ7037AXB_260508_QC_R0.csv')
    assert 'error' not in r
    chips = r['chips_list']
    cid = chips[0]['chip_id']
    assert cid, "chip_id 不应为空"
    assert cid != '?', "chip_id 不应为 '?'"
    # chip_id_1_l 值通常 > 10000，PART_ID 是 1-215
    assert int(cid) > 1000, f"chip_id={cid} 应是硅ID(>1000)，不是PART_ID(1-215)"


def test_get_chip_results_uses_chip_id():
    """get_chip_results 应按 chip_id（硅ID）查找，不是 PART_ID"""
    # chip_id_1_l=11292 在 QC_R0 中对应 PART_ID=14
    result = parser.get_chip_results('11292')
    assert 'error' not in result, f"查找失败: {result.get('error')}"
    assert result['total_rounds_tested'] >= 1
    assert result['chip_id'] == '11292'


def test_find_persistent_fails_uses_chip_id():
    """find_persistent_fails 的 chip_id 应是硅ID"""
    result = parser.find_persistent_fails()
    assert 'error' not in result
    if result['persistent_fail_chips']:
        chip = result['persistent_fail_chips'][0]
        cid = chip['chip_id']
        assert cid.isdigit(), f"chip_id={cid} 应为数字字符串"
        # 至少有一个 chip_id > 215，说明用的是硅 ID
        all_cids = [c['chip_id'] for c in result['persistent_fail_chips']]
        has_silicon_id = any(int(c) > 215 for c in all_cids if c.isdigit())
        assert has_silicon_id, f"应有用硅ID标识的芯片，实际: {all_cids[:5]}"
