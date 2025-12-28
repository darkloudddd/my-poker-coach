/* script.js */
document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatHistory = document.getElementById('chat-history');
    const resetBtn = document.getElementById('reset-btn');
    const strategyContent = document.getElementById('strategy-content');

    // --- Card Selector Elements ---
    const clearCardsBtn = document.getElementById('clear-cards-btn');
    const heroSlots = document.querySelectorAll('[data-slot^="hero-"]');
    const boardSlots = document.querySelectorAll('[data-slot^="board-"]');

    // Auto-resize textarea
    userInput.addEventListener('input', function () {
        this.style.height = 'auto';
        this.style.height = (this.scrollHeight) + 'px';
        if (this.value === '') this.style.height = 'auto';
    });

    // Handle Enter key to submit
    userInput.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event('submit'));
        }
    });

    // --- Card Selector Logic ---
    const suits = [
        { key: 's', icon: 'fa-spade', unicode: '♠', cssClass: 'suit-s' },
        { key: 'h', icon: 'fa-heart', unicode: '♥', cssClass: 'suit-h' },
        { key: 'c', icon: 'fa-clover', unicode: '♣', cssClass: 'suit-c' },
        { key: 'd', icon: 'fa-diamond', unicode: '♦', cssClass: 'suit-d' }
    ];
    const ranks = ['A', 'K', 'Q', 'J', 'T', '9', '8', '7', '6', '5', '4', '3', '2'];
    const validCards = new Set();
    suits.forEach(s => ranks.forEach(r => validCards.add(r + s.key)));



    let currentSlot = null; // Currently active slot element
    let selectedCardMap = new Map(); // slotId -> cardString (e.g. "hero-0" -> "Ah")

    function initCardPicker() {
        // Generate buttons for each suit row
        suits.forEach(suit => {
            const container = document.querySelector(`.ranks[data-suit="${suit.key}"]`);
            if (!container) return;
            container.innerHTML = ''; // Clear
            ranks.forEach(rank => {
                const btn = document.createElement('button');
                btn.className = `card-btn ${suit.cssClass}`;
                // Use span for icon to avoid italicizing or font issues
                btn.innerHTML = `
                    <span>${rank}</span>
                    <span class="suit-char">${suit.unicode}</span>
                `;
                btn.dataset.card = `${rank}${suit.key}`; // e.g. "As"
                btn.onclick = () => selectCard(btn.dataset.card);
                container.appendChild(btn);
            });
        });
    }

    // --- Modal Logic ---
    const modalOverlay = document.getElementById('picker-modal');
    const closeModalBtn = document.getElementById('close-modal-btn');

    function openPicker(slot) {
        console.log('Opening picker for slot:', slot);
        currentSlot = slot;
        // Highlight active slot visual
        document.querySelectorAll('.card-slot').forEach(s => s.classList.remove('active'));
        slot.classList.add('active');

        // Show modal
        modalOverlay.classList.add('open');
    }

    function closePicker() {
        modalOverlay.classList.remove('open');
    }

    // Event Listeners for Modal
    closeModalBtn.addEventListener('click', closePicker);
    modalOverlay.addEventListener('click', (e) => {
        if (e.target === modalOverlay) closePicker();
    });

    [...heroSlots, ...boardSlots].forEach(slot => {
        console.log('Attaching click listener to:', slot);
        slot.addEventListener('click', () => openPicker(slot));
    });

    // Select Card & Close
    function selectCard(cardVal) {
        if (!currentSlot) return;

        // Check availability
        const existingSlot = [...selectedCardMap.entries()].find(([k, v]) => v === cardVal);
        if (existingSlot && existingSlot[0] !== currentSlot.dataset.slot) {
            alert('這張牌已經選過了！');
            return;
        }

        // Fill Slot
        const suitKey = cardVal.slice(-1);
        const isRed = (suitKey === 'h' || suitKey === 'd');
        const rank = cardVal.slice(0, -1);
        const suitObj = suits.find(s => s.key === suitKey);
        const suitChar = suitObj ? suitObj.unicode : '';

        currentSlot.innerHTML = `
            <span>${rank}</span>
            <span style="font-size: 1.2em; margin-left: 2px; line-height: 1;">${suitChar}</span>
        `;
        currentSlot.className = `card-slot filled ${suitObj.cssClass} active`;
        selectedCardMap.set(currentSlot.dataset.slot, cardVal);

        // Update Textarea
        updateInputWithCards();

        // Determine next step
        const slotId = currentSlot.dataset.slot; // e.g. "hero-0"

        let keepOpen = false;

        // Hero Hand: 0 -> 1 (Finish)
        if (slotId === 'hero-0') keepOpen = true;

        // Board Cards: 0 -> 1 -> 2 (Flop Finish)
        if (slotId === 'board-0' || slotId === 'board-1') keepOpen = true;

        // Board Cards: 3 (Turn) -> Close
        // Board Cards: 4 (River) -> Close

        if (keepOpen) {
            advanceSlotFocus(true); // Advance and KEEP Modal
        } else {
            closePicker();
            advanceSlotFocus(false); // Just highlight next
        }
    }

    function advanceSlotFocus(keepOpen) {
        const allSlots = [...heroSlots, ...boardSlots];
        const idx = allSlots.indexOf(currentSlot);
        if (idx !== -1 && idx < allSlots.length - 1) {
            const nextSlot = allSlots[idx + 1];

            // Visual highlight
            document.querySelectorAll('.card-slot').forEach(s => s.classList.remove('active'));
            nextSlot.classList.add('active');

            if (keepOpen) {
                // Update internal pointer for next click
                currentSlot = nextSlot;
                console.log('Auto-advancing to:', currentSlot.dataset.slot);
            }
        }
    }

    function updateInputWithCards() {
        // Construct the card string at the start of the input
        const heroCards = [];
        heroSlots.forEach(s => {
            const card = selectedCardMap.get(s.dataset.slot);
            if (card) heroCards.push(card);
        });

        const boardCards = [];
        boardSlots.forEach(s => {
            const card = selectedCardMap.get(s.dataset.slot);
            if (card) boardCards.push(card);
        });

        let prefix = "";
        if (heroCards.length > 0) prefix += `Hero holds ${heroCards.join(' ')}. `;
        if (boardCards.length > 0) prefix += `Board is ${boardCards.join(' ')}. `;

        // We need to manage this carefully so we don't duplicate or delete user text.
        // For now, let's just PREPEND it if it's not there? 
        // Or simpler: We don't modify the text area LIVE, we modify the payload on SUBMIT?
        // But the user likes to see it. 
        // Let's NOT modify the textarea live to avoid fighting the user.
        // We will append this info silently on submit OR just rely on the user seeing the visual cards.
        // We will append this info silently on submit OR just rely on the user seeing the visual cards.
    }

    function syncVisualState(gameState) {
        if (!gameState) return;

        // 1. Sync Hero Hand
        // Backend keys are "hero_hole_cards" and "board_cards" based on context.py
        const heroCards = gameState.hero_hole_cards || gameState.hero_hand || [];

        heroSlots.forEach((slot, idx) => {
            let cardTitle = heroCards[idx]; // e.g. "As" or "as"
            if (cardTitle) {
                // Normalize to Title Case (e.g. "as" -> "As")
                cardTitle = cardTitle.charAt(0).toUpperCase() + cardTitle.slice(1).toLowerCase();
            }

            if (cardTitle && validCards.has(cardTitle)) {
                fillSlot(slot, cardTitle);
                selectedCardMap.set(slot.dataset.slot, cardTitle);
            } else {
                // Only clear if we are strictly syncing
                if (idx >= heroCards.length) {
                    clearSlot(slot);
                    selectedCardMap.delete(slot.dataset.slot);
                }
            }
        });

        // 2. Sync Board
        const boardCards = gameState.board_cards || gameState.board || [];
        boardSlots.forEach((slot, idx) => {
            let cardTitle = boardCards[idx];
            if (cardTitle) {
                cardTitle = cardTitle.charAt(0).toUpperCase() + cardTitle.slice(1).toLowerCase();
            }

            if (cardTitle && validCards.has(cardTitle)) {
                fillSlot(slot, cardTitle);
                selectedCardMap.set(slot.dataset.slot, cardTitle);
            } else {
                if (idx >= boardCards.length) {
                    clearSlot(slot);
                    selectedCardMap.delete(slot.dataset.slot);
                }
            }
        });
    }

    function fillSlot(slot, cardVal) {
        const suitKey = cardVal.slice(-1);
        const rank = cardVal.slice(0, -1);
        const suitObj = suits.find(s => s.key === suitKey);
        const suitChar = suitObj ? suitObj.unicode : '';

        slot.innerHTML = `
            <span>${rank}</span>
            <span style="font-size: 1.2em; margin-left: 2px; line-height: 1;">${suitChar}</span>
        `;
        slot.className = `card-slot filled ${suitObj.cssClass} active`;
    }

    function clearSlot(slot) {
        slot.className = 'card-slot empty';
        slot.innerHTML = '';
    }


    // Clear
    if (clearCardsBtn) {
        clearCardsBtn.addEventListener('click', () => {
            selectedCardMap.clear();
            [...heroSlots, ...boardSlots].forEach(slot => {
                slot.className = 'card-slot empty';
                slot.innerHTML = '';
            });
        });
    }

    // Initialize logic
    initCardPicker();

    // --- Chat Logic ---

    // Reset Game
    resetBtn.addEventListener('click', async () => {
        if (!confirm('確定要清除當前記憶並開始新牌局嗎？')) return;

        try {
            const res = await fetch('/reset', { method: 'POST' });
            if (res.ok) {
                chatHistory.innerHTML = `
                    <div class="message assistant">
                        <div class="bubble">
                            <p>🧹 記憶已清除，請輸入新牌局。</p>
                        </div>
                    </div>
                `;
                strategyContent.innerHTML = `
                    <div class="empty-state">
                        <i class="fa-solid fa-chart-pie"></i>
                        <p>尚無分析數據</p>
                    </div>
                `;
                // Also clear selections
                selectedCardMap.clear();
                [...heroSlots, ...boardSlots].forEach(slot => { slot.className = 'card-slot empty'; slot.innerHTML = ''; });
            }
        } catch (err) {
            console.error('Reset failed', err);
        }
    });

    // Submit Form
    chatForm.addEventListener('submit', async (e) => {
        e.preventDefault();

        let text = userInput.value.trim();
        // Prepend Card Info if any
        const heroCards = [];
        const boardCards = [];

        heroSlots.forEach(s => {
            const c = selectedCardMap.get(s.dataset.slot);
            if (c) heroCards.push(c);
        });
        boardSlots.forEach(s => {
            const c = selectedCardMap.get(s.dataset.slot);
            if (c) boardCards.push(c);
        });

        let cardPrefix = "";
        if (heroCards.length > 0) cardPrefix += `Hero holds ${heroCards.join('')}. `; // e.g. AhKh
        if (boardCards.length > 0) cardPrefix += `Board is ${boardCards.join('')}. `; // e.g. Ks7d2c

        const fullMessage = (cardPrefix + text).trim();

        if (!fullMessage) return;

        // Show only user text, or a default message if only cards were updated
        const displayMessage = text || "🃏 (更新手牌狀態)";
        addMessage('user', displayMessage);

        userInput.value = '';
        userInput.style.height = 'auto';

        // Show Loading
        const loadingId = addLoadingIndicator();

        try {
            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: fullMessage })
            });

            const data = await response.json();

            // Remove Loading
            removeMessage(loadingId);

            // Add Assistant Message
            if (data.advice) {
                addMessage('assistant', formatResponse(data.advice));
            }

            // Update Analysis Panel
            updateAnalysisPanel(data);

            // Sync Visual State (Important for follow-up questions)
            syncVisualState(data.game_state);


        } catch (err) {
            removeMessage(loadingId);
            addMessage('assistant', '❌ 發生錯誤，請稍後再試。');
            console.error(err);
        }
    });

    function addMessage(role, text) {
        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${role}`;
        msgDiv.innerHTML = `<div class="bubble">${text}</div>`;
        chatHistory.appendChild(msgDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    function addLoadingIndicator() {
        const id = 'loading-' + Date.now();
        const msgDiv = document.createElement('div');
        msgDiv.id = id;
        msgDiv.className = 'message assistant';
        msgDiv.innerHTML = `<div class="bubble"><i class="fa-solid fa-circle-notch fa-spin"></i> 思考中...</div>`;
        chatHistory.appendChild(msgDiv);
        chatHistory.scrollTop = chatHistory.scrollHeight;
        return id;
    }

    function removeMessage(id) {
        const el = document.getElementById(id);
        if (el) el.remove();
    }

    function formatResponse(text) {
        // Configure marked options if needed (optional)
        // marked.use({ breaks: true }); // Enable line breaks
        return marked.parse(text);
    }

    function updateAnalysisPanel(data) {
        const { strategy, game_state } = data;

        if (!strategy && !game_state) return;

        let html = '';

        // Container for Strategy & Frequency (Grid Layout)
        html += '<div class="strategy-grid">';

        // 1. Recommendation (Left Side or Top)
        if (strategy && strategy.recommended_action) {
            const amountStr = strategy.amount > 0 ? strategy.amount.toFixed(1) + ' BB' : '';
            html += `
                <div class="strategy-card recommend-card">
                    <div class="card-header">
                        <i class="fa-solid fa-star"></i> 最佳行動
                    </div>
                    <div class="recommend-body">
                        <div class="main-action">${strategy.recommended_action.toUpperCase()}</div>
                        ${amountStr ? `<div class="sub-action">建議尺寸 <span class="highlight-val">${amountStr}</span></div>` : ''}
                    </div>
                </div>
            `;
        }

        // 2. Strategy Matrix (Frequencies)
        if (strategy && strategy.strategy_matrix) {
            const matrix = strategy.strategy_matrix;
            html += `<div class="strategy-card matrix-card">
                <div class="card-header"><i class="fa-solid fa-chart-simple"></i> 策略分佈</div>
                <div class="matrix-body">`;

            // Sort actions by frequency descending
            const entries = Object.entries(matrix).sort((a, b) => b[1] - a[1]);

            for (const [action, freq] of entries) {
                if (freq < 0.01) continue;
                const pct = (freq * 100).toFixed(0);

                let fillClass = 'fill-neutral';
                if (action.includes('raise') || action.includes('allin')) fillClass = 'fill-raise';
                else if (action.includes('bet')) fillClass = 'fill-bet';
                else if (action.includes('call')) fillClass = 'fill-call';
                else if (action.includes('check')) fillClass = 'fill-check';
                else if (action.includes('fold')) fillClass = 'fill-fold';

                html += `
                    <div class="action-row">
                        <div class="action-info">
                            <span class="act-name">${action.toUpperCase()}</span>
                            <span class="act-pct">${pct}%</span>
                        </div>
                        <div class="progress-bar-bg">
                            <div class="progress-bar-fill ${fillClass}" style="width: ${pct}%"></div>
                        </div>
                    </div>
                `;
            }
            html += `</div></div>`; // Close body, card
        }

        html += '</div>'; // Close strategy-grid

        // 3. Math Data (Separate Card below)
        if (strategy && strategy.context && strategy.context.math_data) {
            const math = strategy.context.math_data;
            // Round numbers
            const spr = math.spr ? (typeof math.spr === 'number' ? math.spr.toFixed(2) : math.spr) : '-';
            const potOdds = math.pot_odds ? (math.pot_odds * 100).toFixed(0) + '%' : '-';
            const callAmt = math.amount_to_call != null ? math.amount_to_call : 0;

            html += `
                <div class="strategy-card math-card">
                    <div class="card-header"><i class="fa-solid fa-calculator"></i> 數據儀表板</div>
                    <div class="math-grid">
                        <div class="math-item">
                            <span class="math-label">SPR</span>
                            <span class="math-val">${spr}</span>
                        </div>
                        <div class="math-item">
                            <span class="math-label">底池賠率</span>
                            <span class="math-val">${potOdds}</span>
                        </div>
                        <div class="math-item">
                            <span class="math-label">跟注額</span>
                            <span class="math-val">${callAmt} <small>BB</small></span>
                        </div>
                    </div>
                </div>
            `;
        }

        strategyContent.innerHTML = html;
    }
});
