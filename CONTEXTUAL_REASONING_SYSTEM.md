# 推理系統

## 核心架構

這是一個**多維度的推理引擎**，基於以下維度進行特定street的決策：

### 推理維度

```
┌─────────────────────────────────────────────┐
│  1. 牌面特性 (Board Structure)              │
│  ├─ Texture: wet/dry/coordinated             │
│  ├─ Connectivity: 連結度 (0-1)              │
│  └─ Tier: 牌力層次 (nuts/strong/medium/weak) │
└─────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────┐
│  2. 牌力分佈 (Strength Distribution)        │
│  ├─ 對手範圍在此牌面的牌力構成                  │
│  ├─ nuts_pct / strong_pct / weak_pct         │
│  └─ 誰的範圍領先 (Hero vs Villain)            │
└─────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────┐
│  3. 行動合理性 (Action Rationality)         │
│  ├─ 期望的行動分佈 (check/bet/raise)         │
│  └─ 實際行動 vs 期望 = 驚訝度                 │
└─────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────┐
│  4. 過濾強度 (Filtering Strength)           │
│  ├─ 基於驚訝度、連結度、領先度                 │
│  ├─ 位置、街道的動態調整                      │
│  └─ 0.55x (激進) 到 1.0x (溫和)              │
└─────────────────────────────────────────────┘
           ↓
┌─────────────────────────────────────────────┐
│  5. 範圍縮減 (Range Filtering)              │
│  ├─ 根據牌力和行動決定每隻手的倍數 (0.05-1.5) │
│  ├─ 應用過濾強度乘數                         │
│  └─ 只保留權重 > 0.5 的手牌                  │
└─────────────────────────────────────────────┘
```

## 關鍵特性

### 1️⃣ 牌面連結性作為主驅動力

不同牌面上，相同的行動有完全不同的含義：

| 牌面 | 連結度 | 對手 CHECK 的含義 | 過濾強度 |
|------|--------|------------------|---------|
| **K♥ Q♦ J♣** | 0.53 | 有點驚訝（can still have broadway） | 0.55x |
| **7♠ 2♣ 5♦** | 0.23 | 很合理（stack小於等） | 0.57x |

**結論**：牌面連結度直接影響過濾決策的激進程度。

### 2️⃣ 街道-特定的推理

每一街都重新評估，而不是盲目套用規則：

```
Preflop: 位置決定初始範圍
  ↓
Flop:    看牌面+範圍的連結性，判斷對手的行動有多驚訝
  ↓
Turn:    基於 Flop 背景，評估 Turn 新牌對"現在範圍"的影響
  ↓
River:   基於前三條街的演變，做最終判斷
```

### 3️⃣ 相對牌力而不是絕對規則

系統考慮：
- **我 vs 對手的牌力差異**：我領先 vs 對手領先會改變行動的解讀
- **範圍的牌力層次**：如果對手的範圍中 nuts 很多，他 bet 就很正常
- **牌力的分化程度**：高度分化的範圍（很多 nuts + 很多 air）的行動信息量更大

### 4️⃣ 可完全追蹤和解釋的推理

每一步都產生清楚的推理文本：

```
TURN: ['5h', '9d', '2c', 'ks'] | 牌面: wet | 連結度: 0.10
對手範圍: 0.9% nuts, 21.5% strong, 68.0% weak
誰領先: Hero
對手 bet: 非常驚訝 (期望: check 66.7%, bet 23.8%)
過濾強度: 0.55x (激進)
```

## 系統流程演示

### 初始狀態
```
BTN Open → 564 combos (91 hand types)
```

### Flop: 5♥ 9♦ 2♣ → Check
```
牌面分析:
  - Texture: wet（低牌多，易成抽牌）
  - Connectivity: 0.13（低，乾牌）
  - 對手牌力: 3.0% nuts, 19.4% strong, 75.5% weak

判斷:
  - 對手 CHECK 很合理（期望: check 66.7%）
  - 過濾強度: 0.59x (溫和)

結果: 564 → 285 combos (-49.4%)
```

### Turn: K♠ → Bet
```
牌面分析:
  - Texture: wet（仍然低牌多）
  - Connectivity: 0.10（非常低）
  - 新增的 K 很重要（對 BTN 的 broadway hands）
  - 對手牌力: 0.9% nuts, 21.5% strong, 68.0% weak（與新牌前比相似）

判斷:
  - 對手 BET 非常驚訝！（期望: check 66.7%, bet 23.8%）
  - 這表示對手很可能有新升級的手牌（KX）或詐唬
  - 過濾強度: 0.55x (激進)

結果: 285 → 49 combos (-82.9%)
```

### River: 3♠ → Check
```
牌面分析:
  - Texture: coordinated（連牌組合）
  - Connectivity: 0.46（相對高）
  - 對手牌力大幅改變: 6.0% nuts, 65.5% strong, 3.2% weak（突然強很多！）
  - 對方現在領先

判斷:
  - 對手 CHECK 非常驚訝！（期望: check 23.8%, bet 61.9%）
  - 但現在對手牌力很強，所以 CHECK 可能是：
    - Slow play strong hand
    - 尋求次佳手牌的 value
    - 或害怕對面更強
  - 過濾強度: 0.55x (激進)

結果: 49 → 7 combos (-84.8%)

最終: 564 → 7 combos (98.7% 累積縮減)
```

## 核心模塊

### 1. `board_structure.py`
```python
class BoardStructure:
  - classify_texture()     # 公牌特性：wet/dry/coordinated
  - measure_connectivity() # 牌面抽牌豐富度
  - analyze_tiers()        # 牌力層次分析
```

### 2. `strength_analyzer.py`
```python
class StrengthAnalyzer:
  - evaluate_hand_on_board()       # 手牌在此牌面的牌力
  - analyze_range_distribution()   # 整個範圍的牌力分佈
  - compare_ranges_at_board()      # 相對牌力比較

class ActionRationality:
  - get_reasonable_actions()       # 根據牌力決定合理行動
  - action_surprise_factor()       # 計算行動的驚訝度
```

### 3. `contextual_reasoner.py`
```python
class ContextualReasoner:
  - reason_street()                # 完整的街道推理
  - _calculate_filtering_adjustment() # 決定過濾強度
  - _filter_range()                # 實際過濾範圍
  - _get_action_multiplier()       # 根據牌力和行動的倍數
```

## 參數調整

所有策略參數都可調整以改變系統行為：

```python
# board_structure.py
connectivity_weights = {
    "gap_score": 0.6,
    "flush_potential": 0.4
}

# contextual_reasoner.py
_calculate_filtering_adjustment() 可調整：
  - surprise_factor 的分檔 (0.7, 0.4, 0.1)
  - connectivity_factor 的權重 (0.3)
  - 街道特定的 street_factor

_get_action_multiplier() 可調整每個（手牌強度, 行動）組合的倍數
```