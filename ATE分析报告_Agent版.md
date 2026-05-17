# ATE数据分析报告

# WQ7037AXB 芯片ATE测试数据诊断报告

## 一、测试概况

本批次共 **215颗** WQ7037AXB芯片，经历了4轮轮次测试：
- **FT_R0**（出厂初测）：215颗
- **QC_R0**（质量确认第0轮）：215颗中FAIL的芯片复测（文件记录451条，含多轮汇总数据）
- **QC_R1**（质量确认第1轮）：82颗复测
- **QC_R2**（质量确认第2轮）：6颗再复测

| 轮次 | 测试芯片数 | PASS | FAIL | 良率 |
|------|-----------|------|------|------|
| FT_R0 | 215 | 200 | 15 | **93.0%** |
| QC_R0* | 449 | 367 | 82 | 81.7% |
| QC_R1 | 82 | 76 | 6 | **92.7%** |
| QC_R2 | 6 | 3 | 3 | 50.0% |

> *QC_R0文件包含451条记录，实际被测物理芯片为原215颗中的FAIL芯片及追加复测芯片。

---

## 二、各轮次Fail Bin分布

### 2.1 FT_R0 — 初测FAIL（15颗）

| Bin | 测试项 | 数量 | 占比 |
|-----|--------|------|------|
| 62 | mbist (存储器内建自测试) | 3 | 1.40% |
| 7305 | xtal_25u (晶振25μA) | 3 | 1.40% |
| 96 | shutdown (关断测试) | 2 | 0.93% |
| 7500 | rf_img (射频镜像抑制) | 2 | 0.93% |
| 60 | dc_scan (直流扫描) | 1 | 0.47% |
| 70 | uvp_flag (欠压保护标志) | 1 | 0.47% |
| 7103 | dc12 (DC12电源) | 1 | 0.47% |
| 7219 | I_chg_100ma_V4P0 (充电电流) | 1 | 0.47% |
| 7515 | tx_edr_pwr (发射EDR功率) | 1 | 0.47% |

### 2.2 QC_R0 — 质量确认（82 FAIL）

| Bin | 测试项 | 数量 | 占比 |
|-----|--------|------|------|
| 54 | **io_test (IO测试)** | **53** | **11.80%** |
| 7710 | lbk_mic0 (音频回环MIC0) | 8 | 1.78% |
| 61 | ac_scan (交流扫描) | 5 | 1.11% |
| 40 | io_openshort (IO开短路) | 4 | 0.89% |
| 其他 | rf_img, tx_horm等 | 12 | 2.68% |

> ⚠️ **QC_R0的io_test异常**：53颗芯片（11.8%）因io_test fail，但QC_R1中该问题未再现。这可能表明io_test存在测试接触问题或测试环境波动，而非芯片硬件缺陷。

### 2.3 QC_R1 — 复测（6 FAIL）
- lbk_mic0(2), ac_scan(1), dc12(1), rx_iqm(1), lbk_mic1(1)

### 2.4 QC_R2 — 再复测（3 FAIL）
- lbk_mic0(1), dc12(1), rx_iqm(1)

---

## 三、跨轮次持续Fail分析（核心发现） ⭐

通过 `find_persistent_fails` 在≥2轮中持续fail的芯片**共17颗**。TOP持续fail测试项：

| 排名 | 测试项 | 影响芯片数 | 风险等级 |
|------|--------|-----------|---------|
| 1 | **音频MIC1偏置电阻** (ptd_sts_audio_mic1_re) | 12 | 🔴 高 |
| 2 | **音频MIC0偏置电阻** (ptd_sts_audio_mic0_re) | 10 | 🔴 高 |
| 3 | **音频MIC2偏置电阻** (ptd_sts_audio_mic2_re) | 10 | 🔴 高 |
| 4 | RF接收电流 (ptd_sts_rf_rx_dc_i_ma) | 1 | 🔴 高 |
| 5 | DC12电源电压 (ptd_VDD12) | 1 | 🔴 高 |

### 3.1 🔴 重点关注芯片

#### 芯片 #11531 — RF接收电流持续超标（硬件缺陷高置信度）
| 轮次 | 测试项 | 测量值 | 规格 | 结果 |
|------|--------|--------|------|------|
| FT_R0 | - | - | - | ✅ PASS |
| QC_R0 | rf_rx_dc_i_ma | **61.0 mA** | 0~60mA | ❌ FAIL |
| QC_R1 | rf_rx_dc_i_ma | **63.0 mA** | 0~60mA | ❌ FAIL |
| QC_R2 | rf_rx_dc_i_ma | **67.0 mA** | 0~60mA | ❌ FAIL |

> **诊断**：RF接收电流从61→63→67mA逐步恶化，超过规格上限60mA，且呈单调上升趋势。这是典型的**硬件退化信号**，可能原因：RF前端漏电流增大、内部偏置电路退化。**建议报废处理**。

#### 芯片 #11655 — DC12电源电压持续偏低（硬件缺陷高置信度）
| 轮次 | 测试项 | 测量值 | 规格 | 结果 |
|------|--------|--------|------|------|
| FT_R0 | - | - | - | ✅ PASS |
| QC_R0 | DC12_ocl_3p4 | **1.173 V** | 1.274~1.336V | ❌ FAIL |
| QC_R1 | DC12_ocl_3p4 | **0.987 V** | 1.274~1.336V | ❌ FAIL |
| QC_R2 | DC12_ocl_3p4 | **0.975 V** | 1.274~1.336V | ❌ FAIL |

> **诊断**：DC12电压严重偏低（远低于1.274V下限），且从1.17→0.99→0.98V持续恶化。可能原因：内部LDO／DC-DC模块损坏、电源域短路或漏电。**建议报废处理**。

#### 芯片 #11087 — 音频MIC全通道持续fail（硬件缺陷）
| 轮次 | 测试项 | 测量值 | 规格 | 结果 |
|------|--------|--------|------|------|
| QC_R1 | mic0_re | 88.0 | 90~100 | ❌ FAIL |
| QC_R1 | mic1_re | 89.4~89.8 | 90~100 | ❌ FAIL |
| QC_R1 | mic2_re | 89.2~89.6 | 90~100 / 100~110 | ❌ FAIL |
| QC_R2 | mic0_re | 61.0 / -65.9 | 90~100 / -110~-90 | ❌ FAIL |
| QC_R2 | mic1_re | 63.0 / -68.0 | 90~100 / -110~-90 | ❌ FAIL |
| QC_R2 | mic2_re | 66.0~76.2 / -71.0 | 90~100 / -110~-90 | ❌ FAIL |

> **诊断**：QC_R2中MIC偏置电阻测量值进一步恶化（从88~89恶化到61~66），全三通道持续fail。音频模拟前端可能存在芯片级缺陷。**建议报废处理**。

#### 芯片 #11486 — 音频MIC + AC_SCAN复合fail
| 轮次 | 结果 | 详情 |
|------|------|------|
| FT_R0 | ✅ PASS | - |
| QC_R0 | ❌ FAIL (24项) | mic0/mic1/mic2_re多项fail，值严重偏离（20~85 vs 规格34~100） |
| QC_R1 | ❌ FAIL (1项) | **AC_SCAN** fail (DFT扫描链测试) |
| QC_R2 | ✅ PASS | - |

> **诊断**：QC_R0音频指标严重异常（24项fail），QC_R1又出现AC_SCAN fail（扫描链测试异常）。虽然QC_R2 PASS，但AC_SCAN fail提示芯片可能存在**数字逻辑／扫描链间歇性问题**。**建议标记为可疑，优先确认是否放行**。

---

## 四、总结与建议

### 4.1 最终良率评估
- 从FT_R0初测215颗，200颗PASS（93.0%）
- 多轮QC复测后，最终仍有**3颗芯片**在QC_R2持续FAIL（11531、11655、11087中的至少3颗）
- **最终可用芯片约197~200颗**，整体良率约 **91.6%~93.0%**

### 4.2 问题根因分类

| 类别 | 芯片数 | 典型芯片 | 问题描述 |
|------|--------|---------|---------|
| 🔴 **确凿硬件缺陷** | 3 | 11531, 11655, 11087 | RF电流/DC12电压/音频MIC持续恶化 |
| 🟡 **音频MIC疑似问题** | ~10 | 11486, 11505, 11506等 | 多芯片音频MIC偏置电阻持续fail，可能在某个电平时边界fail |
| 🟠 **扫描链间歇性fail** | ~5 | 11486等 | AC_SCAN/DC_SCAN在不同轮次间或PASS或FAIL |
| 🟢 **测试噪声/接触问题** | ~53 | - | QC_R0 io_test大量fail，复测未再现 |

### 4.3 建议措施
1. **立即报废**：芯片#11531、#11655、#11087（确凿硬件缺陷，持续恶化）
2. **重点审查**：音频MIC持续fail的10颗芯片，需结合应用场景决定是否放行（若产品不使用模拟MIC，可能可接受）
3. **优化测试**：QC_R0的io_test 53颗fail建议排查测试夹具接触问题，53颗在后续复测中消失说明高度可疑是测试环境而非芯片问题
4. **扫描链fail**：DFT扫描链fail的芯片（ac_scan/dc_scan）建议增加Burn-in后复测，排除潜在可靠性风险
5. **数据记录项**：所有100% fail的`ptd_done_bitmap`、`ptd_ate_cali_*`、`ptd_sts_*`类测试项实为数据记录标志位，非功能测试，建议从fail统计中排除，避免干扰良率计算

---

*报告生成时间：基于ATE测试数据系统自动分析*  
*数据来源：4个CSV数据文件，215颗WQ7037AXB芯片，共4轮测试*

---
## Agent分析日志

```

--- Step 1 ---
[思考] 用户要求分析ATE测试数据，重点关注跨轮次持续fail的芯片。按照强制分析流程，我先从整体数据概况入手。

第一步：获取整体良率汇总。
[工具: get_summary_stats]
[观察] get_summary_stats 返回: {
  "note": "⚠️ 所有轮次是同一批芯片(215颗)的重复测量，不是独立批次。不要累加各轮次的芯片数。",
  "rounds": {
    "FT_R0": {
      "total_chips": 215,
      "pass": 200,
      "fail": 15,
      "yield_rate": "93.0%",
      "fail_bins": [
        {
          "bin": "62",
          "name": "mbist",
          "count": 3,
          "pct": "1.40%"
        },
        {
          "bin": "7305",
          "name": "xtal_25u",
          "count": 3,
          "pct": "1.40%"
        },
        {
          "bin": "96",
          "name": "shutdown",
          "count": 2,
          "pct": "0.93%"
        },
        {
          "bin": "7500",
 

--- Step 2 ---
[思考] 整体数据已获取。FT_R0良率93%，QC_R0良率81.7%（io_test fail 53颗非常突出），QC_R1良率92.7%，QC_R2良率50%。现在需要列出具体数据文件，然后深入分析每个轮次的fail项。

第二步：列出数据文件。
[工具: list_data_files]
[观察] list_data_files 返回: {
  "files": [
    {
      "filename": "WQ7037AXB_200_260508_FT_R0.csv",
      "test_type": "R0",
      "round": "R0",
      "chips": 215,
      "test_items": 963,
      "fail_items": 251
    },
    {
      "filename": "WQ7037AXB_260508_QC_R0.csv",
      "test_type": "R0",
      "round": "R0",
      "chips": 451,
      "test_items": 892,
      "fail_items": 555
    },
    {
      "filename": "WQ7037AXB_260508_QC_R1.csv",
      "test_type": "R1",
      "round": "R1",
      "chips": 82,
      "test_items": 892,
      "fail_items": 108
    },
    {
      "filename": "WQ7037AXB_260508_QC_R2.csv",


--- Step 3 ---
[思考] 四个轮次数据文件已列出。FT_R0有215芯片/251 fail项，QC_R0有451芯片（可能是QC_R0+QC_R1+QC_R2的汇总？但文件名是QC_R0单独文件）、QC_R1有82芯片、QC_R2有6芯片。现在按流程第三步，对每个有fail的轮次分析fail详情。先从FT_R0开始。

[工具: analyze_fail_items]
{"filename": "WQ7037AXB_200_260508_FT_R0.csv"}
[观察] analyze_fail_items 返回: {
  "filename": "WQ7037AXB_200_260508_FT_R0.csv",
  "total_chips": 215,
  "total_test_items": 963,
  "fail_item_count": 251,
  "note": "⚠️ fail_chip_ids中的ID是chip_id(硅ID)，同一ID在不同轮次文件中是同一颗物理芯片，可用于跨轮次追踪。",
  "top_fails": [
    {
      "test_item": "ANALOG.Charger_trim.Charger_Triming.ptd_value_S0_1",
      "spec": "3~11mA",
      "fail_count": 215,
      "fail_rate": "100.0%",
      "fail_chip_ids": [
        "11450",
        "11451",
        "11452",
        "11453",
        "11454"
      ],
      "avg_fail_value": "1.4879"
    },
    {
      "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_done_b

--- Step 4 ---
[思考] FT_R0的TOP10 fail项全部是100% fail的项（如ptd_done_bitmap等），这些看起来是数据记录/标志位，并非真正的功能测试fail。真正需要关注的fail项在get_summary_stats中按Bin分类的部分（mbist、xtal_25u等）。现在继续分析QC_R0。

[工具: analyze_fail_items]
{"filename": "WQ7037AXB_260508_QC_R0.csv"}
[观察] analyze_fail_items 返回: {
  "filename": "WQ7037AXB_260508_QC_R0.csv",
  "total_chips": 451,
  "total_test_items": 892,
  "fail_item_count": 555,
  "note": "⚠️ fail_chip_ids中的ID是chip_id(硅ID)，同一ID在不同轮次文件中是同一颗物理芯片，可用于跨轮次追踪。",
  "top_fails": [
    {
      "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_done_bitmap_rf_fl",
      "spec": "12256~12256",
      "fail_count": 393,
      "fail_rate": "87.1%",
      "fail_chip_ids": [
        "11326",
        "11324",
        "11321",
        "11316",
        "11314"
      ],
      "avg_fail_value": "3825.0000"
    },
    {
      "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_don

--- Step 5 ---
[工具: analyze_fail_items]
{"filename": "WQ7037AXB_260508_QC_R1.csv"}
[观察] analyze_fail_items 返回: {
  "filename": "WQ7037AXB_260508_QC_R1.csv",
  "total_chips": 82,
  "total_test_items": 892,
  "fail_item_count": 108,
  "note": "⚠️ fail_chip_ids中的ID是chip_id(硅ID)，同一ID在不同轮次文件中是同一颗物理芯片，可用于跨轮次追踪。",
  "top_fails": [
    {
      "test_item": "ANALOG.Charger_trim.Charger_Triming.ptd_value_S0_1",
      "spec": "2~12mA",
      "fail_count": 82,
      "fail_rate": "100.0%",
      "fail_chip_ids": [
        "11067",
        "11069",
        "11087",
        "11102",
        "11117"
      ],
      "avg_fail_value": "1.6216"
    },
    {
      "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_done_bitmap_

--- Step 6 ---
[工具: analyze_fail_items]
{"filename": "WQ7037AXB_260508_QC_R2.csv"}
[观察] analyze_fail_items 返回: {
  "filename": "WQ7037AXB_260508_QC_R2.csv",
  "total_chips": 6,
  "total_test_items": 877,
  "fail_item_count": 104,
  "note": "⚠️ fail_chip_ids中的ID是chip_id(硅ID)，同一ID在不同轮次文件中是同一颗物理芯片，可用于跨轮次追踪。",
  "top_fails": [
    {
      "test_item": "ANALOG.Charger_trim.Charger_Triming.ptd_value_S0_1",
      "spec": "2~12mA",
      "fail_count": 6,
      "fail_rate": "100.0%",
      "fail_chip_ids": [
        "11456",
        "11486",
        "11655",
        "11531",
        "11307"
      ],
      "avg_fail_value": "1.6059"
    },
    {
      "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_done_bitmap_rf

--- Step 7 ---
[思考] 四个轮次的fail详情都已分析。注意分析出的TOP10 fail项主要是数据记录/标志位类型的项（ptd_done_bitmap、ptd_sts_*等），100%芯片在这些项上"fail"实际上是数据格式问题，不是真正的功能故障。真正的功能fail在get_summary_stats的Fail Bin中。现在进入核心第四步：跨轮次持续fail分析。

[工具: find_persistent_fails]
{"min_rounds": 2}
[观察] find_persistent_fails 返回: {
  "total_chips_analyzed": 464,
  "persistent_fail_count": 17,
  "min_rounds_threshold": 2,
  "summary": "共464颗芯片中，17颗在≥2轮中存在持续fail项；TOP持续fail测试项: ANALOG.Dump_Datalog.ptdGroup.ptd_sts_audio_mic1_re, ANALOG.Dump_Datalog.ptdGroup.ptd_sts_audio_mic0_re, ANALOG.Dump_Datalog.ptdGroup.ptd_sts_audio_mic2_re",
  "persistent_chips": [
    {
      "chip_id": "11456",
      "persistent_fail_items": [
        {
          "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_sts_audio_mic0_re",
          "fail_rounds": [
            "R1",
            "R1",
            "R1",
            "R1"
          ],
        

--- Step 8 ---
[思考] 跨轮次分析结果非常关键。发现17颗芯片有持续fail项。TOP持续fail项集中在音频MIC测试（ptd_sts_audio_mic*_re），涉及10~12颗芯片。另外还有RF接收电流（11531）、DC12电源（11655）等真正硬件相关的持续fail。现在第五步：追踪重点芯片。先追踪涉及RF问题的11531。

[工具: track_chip_across_rounds]
{"chip_id": "11531"}
[观察] track_chip_across_rounds 返回: {
  "chip_id": "11531",
  "total_rounds_tested": 4,
  "rounds": [
    {
      "filename": "WQ7037AXB_200_260508_FT_R0.csv",
      "round": "R0",
      "hard_bin": "1",
      "soft_bin": "1",
      "pass_fail": "P",
      "fail_count": 0,
      "fail_items": []
    },
    {
      "filename": "WQ7037AXB_260508_QC_R0.csv",
      "round": "R0",
      "hard_bin": "7",
      "soft_bin": "7503",
      "pass_fail": "F",
      "fail_count": 1,
      "fail_items": [
        {
          "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_sts_rf_rx_dc_i_ma",
          "value": 61.0,
          "spec": "0~60"
  

--- Step 9 ---
[工具: track_chip_across_rounds]
{"chip_id": "11655"}
[观察] track_chip_across_rounds 返回: {
  "chip_id": "11655",
  "total_rounds_tested": 4,
  "rounds": [
    {
      "filename": "WQ7037AXB_200_260508_FT_R0.csv",
      "round": "R0",
      "hard_bin": "1",
      "soft_bin": "1",
      "pass_fail": "P",
      "fail_count": 0,
      "fail_items": []
    },
    {
      "filename": "WQ7037AXB_260508_QC_R0.csv",
      "round": "R0",
      "hard_bin": "7",
      "soft_bin": "7103",
      "pass_fail": "F",
      "fail_count": 1,
      "fail_items": [
        {
          "test_item": "ANALOG.PMU_trim.DC12_ocl_3p4.ptd_VDD12",
          "value": 1.173378,
          "spec": "1.274~1.336"
   

--- Step 10 ---
[工具: track_chip_across_rounds]
{"chip_id": "11087"}
[观察] track_chip_across_rounds 返回: {
  "chip_id": "11087",
  "total_rounds_tested": 2,
  "rounds": [
    {
      "filename": "WQ7037AXB_260508_QC_R1.csv",
      "round": "R1",
      "hard_bin": "7",
      "soft_bin": "7710",
      "pass_fail": "F",
      "fail_count": 7,
      "fail_items": [
        {
          "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_sts_audio_mic0_re",
          "value": 88.0,
          "spec": "90~100"
        },
        {
          "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_sts_audio_mic0_re",
          "value": 88.0,
          "spec": "90~100"
        },
        {
          "test_item": "ANALOG.

--- Step 11 ---
[工具: track_chip_across_rounds]
{"chip_id": "11486"}
[观察] track_chip_across_rounds 返回: {
  "chip_id": "11486",
  "total_rounds_tested": 4,
  "rounds": [
    {
      "filename": "WQ7037AXB_200_260508_FT_R0.csv",
      "round": "R0",
      "hard_bin": "1",
      "soft_bin": "1",
      "pass_fail": "P",
      "fail_count": 0,
      "fail_items": []
    },
    {
      "filename": "WQ7037AXB_260508_QC_R0.csv",
      "round": "R0",
      "hard_bin": "7",
      "soft_bin": "7710",
      "pass_fail": "F",
      "fail_count": 24,
      "fail_items": [
        {
          "test_item": "ANALOG.Dump_Datalog.ptdGroup.ptd_sts_audio_mic0_re",
          "value": 20.0,
          "spec": "36~50"


--- Step 12 ---
[工具: compare_files]
{"filenames": ["WQ7037AXB_200_260508_FT_R0.csv", "WQ7037AXB_260508_QC_R0.csv", "WQ7037AXB_260508_QC_R1.csv", "WQ7037AXB_260508_QC_R2.csv"]}
[观察] compare_files 返回: {
  "comparison": [
    {
      "filename": "WQ7037AXB_200_260508_FT_R0.csv",
      "type": "R0",
      "chips": 215,
      "test_items": 963,
      "fail_items": 251
    },
    {
      "filename": "WQ7037AXB_260508_QC_R0.csv",
      "type": "R0",
      "chips": 451,
      "test_items": 892,
      "fail_items": 555
    },
    {
      "filename": "WQ7037AXB_260508_QC_R1.csv",
      "type": "R1",
      "chips": 82,
      "test_items": 892,
      "fail_items": 108
    },
    {
      "filename": "WQ7037AXB_260508_QC_R2.csv",
      "type": "R2",
      "chips": 6,
      "test_items": 877,
      "fai

--- Step 13 ---
[最终报告]

# WQ7037AXB 芯片ATE测试数据诊断报告

## 一、测试概况

本批次共 **215颗** WQ7037AXB芯片，经历了4轮轮次测试：
- **FT_R0**（出厂初测）：215颗
- **QC_R0**（质量确认第0轮）：215颗中FAIL的芯片复测（文件记录451条，含多轮汇总数据）
- **QC_R1**（质量确认第1轮）：82颗复测
- **QC_R2**（质量确认第2轮）：6颗再复测

| 轮次 | 测试芯片数 | PASS | FAIL | 良率 |
|------|-----------|------|------|------|
| FT_R0 | 215 | 200 | 15 | **93.0%** |
| QC_R0* | 449 | 367 | 82 | 81.7% |
| QC_R1 | 82 | 76 | 6 | **92.7%** |
| QC_R2 | 6 | 3 | 3 | 50.0% |

> *QC_R0文件包含451条记录，实际被测物理芯片为原215颗中的FAIL芯片及追加复测芯片。

---

## 二、各轮次Fail Bin分布

### 2.1 FT_R0 — 初测FAIL（15颗）

| Bin | 测试项 | 数量 | 占比 |
|-----|--------|------|------|
| 62 | mbist (存储器内建自测试) | 3 | 1.40% |
| 7305 | xtal_25u (晶振25μA) | 3 | 1.40% |
| 96 | shutdown (关断测试) | 2 | 0.93% |
| 7500 | rf_img (射频镜像抑制) | 2 | 0.93% |
| 60 | dc_scan (直流扫描) | 1 | 0.47% |
| 70 | uvp_flag (欠压保护标志) | 1 | 0.47% |
| 7103 | dc12 (DC12电源) | 1 | 0.47% |
| 7219 | I_chg_100ma_V4P0 (充电电流) | 1 | 0.47% |
| 7515 | tx_edr_pwr (发射EDR功率) | 1 | 0.47% |

### 2.2 QC_R0 — 质量确认（82 FAIL）

| Bin | 测试项 | 数量 | 占比 |
|-----|--------|------|------|
| 54 | **io_test (IO测试)** | **53** | **11.80%** |
| 7710 | lbk_mic0 (音频回环MIC0) | 8 | 1.78% |
| 61 | ac_scan (交流扫描) | 5 | 1.11% |
| 40 | io_openshort (IO开短路) | 4 | 0.89% |
| 其他 | rf_img, tx_horm等 | 12 | 2.68% |

> ⚠️ **QC_R0的io_test异常**：53颗芯片（11.8%）因io_test fail，但QC_R1中该问题未再现。这可能表明io_test存在测试接触问题或测试环境波动，而非芯片硬件缺陷。

### 2.3 QC_R1 — 复测（6 FAIL）
- lbk_mic0(2), ac_scan(1), dc12(1), rx_iqm(1), lbk_mic1(1)

### 2.4 QC_R2 — 再复测（3 FAIL）
- lbk_mic0(1), dc12(1), rx_iqm(1)

---

## 三、跨轮次持续Fail分析（核心发现） ⭐

通过 `find_persistent_fails` 在≥2轮中持续fail的芯片**共17颗**。TOP持续fail测试项：

| 排名 | 测试项 | 影响芯片数 | 风险等级 |
|------|--------|-----------|---------|
| 1 | **音频MIC1偏置电阻** (ptd_sts_audio_mic1_re) | 12 | 🔴 高 |
| 2 | **音频MIC0偏置电阻** (ptd_sts_audio_mic0_re) | 10 | 🔴 高 |
| 3 | **音频MIC2偏置电阻** (ptd_sts_audio_mic2_re) | 10 | 🔴 高 |
| 4 | RF接收电流 (ptd_sts_rf_rx_dc_i_ma) | 1 | 🔴 高 |
| 5 | DC12电源电压 (ptd_VDD12) | 1 | 🔴 高 |

### 3.1 🔴 重点关注芯片

#### 芯片 #11531 — RF接收电流持续超标（硬件缺陷高置信度）
| 轮次 | 测试项 | 测量值 | 规格 | 结果 |
|------|--------|--------|------|------|
| FT_R0 | - | - | - | ✅ PASS |
| QC_R0 | rf_rx_dc_i_ma | **61.0 mA** | 0~60mA | ❌ FAIL |
| QC_R1 | rf_rx_dc_i_ma | **63.0 mA** | 0~60mA | ❌ FAIL |
| QC_R2 | rf_rx_dc_i_ma | **67.0 mA** | 0~60mA | ❌ FAIL |

> **诊断**：RF接收电流从61→63→67mA逐步恶化，超过规格上限60mA，且呈单调上升趋势。这是典型的**硬件退化信号**，可能原因：RF前端漏电流增大、内部偏置电路退化。**建议报废处理**。

#### 芯片 #11655 — DC12电源电压持续偏低（硬件缺陷高置信度）
| 轮次 | 测试项 | 测量值 | 规格 | 结果 |
|------|--------|--------|------|------|
| FT_R0 | - | - | - | ✅ PASS |
| QC_R0 | DC12_ocl_3p4 | **1.173 V** | 1.274~1.336V | ❌ FAIL |
| QC_R1 | DC12_ocl_3p4 | **0.987 V** | 1.274~1.336V | ❌ FAIL |
| QC_R2 | DC12_ocl_3p4 | **0.975 V** | 1.274~1.336V | ❌ FAIL |

> **诊断**：DC12电压严重偏低（远低于1.274V下限），且从1.17→0.99→0.98V持续恶化。可能原因：内部LDO／DC-DC模块损坏、电源域短路或漏电。**建议报废处理**。

#### 芯片 #11087 — 音频MIC全通道持续fail（硬件缺陷）
| 轮次 | 测试项 | 测量值 | 规格 | 结果 |
|------|--------|--------|------|------|
| QC_R1 | mic0_re | 88.0 | 90~100 | ❌ FAIL |
| QC_R1 | mic1_re | 89.4~89.8 | 90~100 | ❌ FAIL |
| QC_R1 | mic2_re | 89.2~89.6 | 90~100 / 100~110 | ❌ FAIL |
| QC_R2 | mic0_re | 61.0 / -65.9 | 90~100 / -110~-90 | ❌ FAIL |
| QC_R2 | mic1_re | 63.0 / -68.0 | 90~100 / -110~-90 | ❌ FAIL |
| QC_R2 | mic2_re | 66.0~76.2 / -71.0 | 90~100 / -110~-90 | ❌ FAIL |

> **诊断**：QC_R2中MIC偏置电阻测量值进一步恶化（从88~89恶化到61~66），全三通道持续fail。音频模拟前端可能存在芯片级缺陷。**建议报废处理**。

#### 芯片 #11486 — 音频MIC + AC_SCAN复合fail
| 轮次 | 结果 | 详情 |
|------|------|------|
| FT_R0 | ✅ PASS | - |
| QC_R0 | ❌ FAIL (24项) | mic0/mic1/mic2_re多项fail，值严重偏离（20~85 vs 规格34~100） |
| QC_R1 | ❌ FAIL (1项) | **AC_SCAN** fail (DFT扫描链测试) |
| QC_R2 | ✅ PASS | - |

> **诊断**：QC_R0音频指标严重异常（24项fail），QC_R1又出现AC_SCAN fail（扫描链测试异常）。虽然QC_R2 PASS，但AC_SCAN fail提示芯片可能存在**数字逻辑／扫描链间歇性问题**。**建议标记为可疑，优先确认是否放行**。

---

## 四、总结与建议

### 4.1 最终良率评估
- 从FT_R0初测215颗，200颗PASS（93.0%）
- 多轮QC复测后，最终仍有**3颗芯片**在QC_R2持续FAIL（11531、11655、11087中的至少3颗）
- **最终可用芯片约197~200颗**，整体良率约 **91.6%~93.0%**

### 4.2 问题根因分类

| 类别 | 芯片数 | 典型芯片 | 问题描述 |
|------|--------|---------|---------|
| 🔴 **确凿硬件缺陷** | 3 | 11531, 11655, 11087 | RF电流/DC12电压/音频MIC持续恶化 |
| 🟡 **音频MIC疑似问题** | ~10 | 11486, 11505, 11506等 | 多芯片音频MIC偏置电阻持续fail，可能在某个电平时边界fail |
| 🟠 **扫描链间歇性fail** | ~5 | 11486等 | AC_SCAN/DC_SCAN在不同轮次间或PASS或FAIL |
| 🟢 **测试噪声/接触问题** | ~53 | - | QC_R0 io_test大量fail，复测未再现 |

### 4.3 建议措施
1. **立即报废**：芯片#11531、#11655、#11087（确凿硬件缺陷，持续恶化）
2. **重点审查**：音频MIC持续fail的10颗芯片，需结合应用场景决定是否放行（若产品不使用模拟MIC，可能可接受）
3. **优化测试**：QC_R0的io_test 53颗fail建议排查测试夹具接触问题，53颗在后续复测中消失说明高度可疑是测试环境而非芯片问题
4. **扫描链fail**：DFT扫描链fail的芯片（ac_scan/dc_scan）建议增加Burn-in后复测，排除潜在可靠性风险
5. **数据记录项**：所有100% fail的`ptd_done_bitmap`、`ptd_ate_cali_*`、`ptd_sts_*`类测试项实为数据记录标志位，非功能测试，建议从fail统计中排除，避免干扰良率计算

---

*报告生成时间：基于ATE测试数据系统自动分析*  
*数据来源：4个CSV数据文件，215颗WQ7037AXB芯片，共4轮测试*
```
