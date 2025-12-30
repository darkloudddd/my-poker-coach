/* script.js */
document.addEventListener('DOMContentLoaded', () => {
    const chatForm = document.getElementById('chat-form');
    const userInput = document.getElementById('user-input');
    const chatHistory = document.getElementById('chat-history');
    const resetBtn = document.getElementById('reset-btn');
    const strategyContent = document.getElementById('strategy-content');
    const sendBtn = document.getElementById('send-btn'); // FIXED: Add missing definition

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

        slot.addEventListener('click', () => openPicker(slot));
    });

    // Select Card & Close
    function selectCard(cardVal) {
        if (!currentSlot) return;

        // Check availability
        const existingSlotEntry = [...selectedCardMap.entries()].find(([k, v]) => v === cardVal);
        if (existingSlotEntry && existingSlotEntry[0] !== currentSlot.dataset.slot) {
            // Already selected elsewhere: Steal it! (Better UX)
            const oldSlotId = existingSlotEntry[0];
            const oldSlot = [...heroSlots, ...boardSlots].find(s => s.dataset.slot === oldSlotId);
            if (oldSlot) {
                clearSlot(oldSlot);
            }
            selectedCardMap.delete(oldSlotId);
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

    const EMPTY_STATE_HTML = `
        <div class="empty-state">
            <div class="empty-icon"><i class="fa-solid fa-chart-pie"></i></div>
            <h3>等待局勢分析...</h3>
            <p>請在左側輸入手牌與行動，<br>AI教練將在此處顯示即時策略建議。</p>
        </div>
    `;

    // Request Generation Counter to prevent race conditions
    let currentGeneration = 0;

    // Reset Game
    // Reset Game
    resetBtn.addEventListener('click', async () => {
        if (!confirm('確定要清除當前記憶並開始新牌局嗎？')) return;

        // Invalidate any pending requests
        currentGeneration++;

        // Stop any ongoing thinking immediately
        stopPolling();

        // Ensure inputs are unlocked and focused for new round
        userInput.disabled = false;
        sendBtn.disabled = false;
        userInput.focus();

        resetBtn.disabled = true; // Disable to prevent double click
        resetBtn.classList.add('disabled-btn');

        try {
            const res = await fetch('/reset', { method: 'POST' });
            if (res.ok) {
                chatHistory.innerHTML = `
                    <div class="message assistant">
                        <div class="bubble">
                            <p>🧹 記憶已清除,請輸入新牌局。</p>
                        </div>
                    </div>
                `;
                strategyContent.innerHTML = EMPTY_STATE_HTML;
                // Also clear selections
                selectedCardMap.clear();
                [...heroSlots, ...boardSlots].forEach(slot => { slot.className = 'card-slot empty'; slot.innerHTML = ''; });
            } else {
                console.error('Reset failed with status:', res.status);
                alert('重置失敗，請稍後再試。');
            }
        } catch (err) {
            console.error('Reset failed', err);
            alert('重置發生錯誤: ' + err.message);
        } finally {
            resetBtn.disabled = false;
            resetBtn.classList.remove('disabled-btn');
        }
    });

    // Shutdown System
    const shutdownBtn = document.getElementById('fixed-shutdown-btn');
    if (shutdownBtn) {
        shutdownBtn.addEventListener('click', async () => {
            if (!confirm('確定要關閉系統嗎？\n(伺服器將停止運作，視窗將無法再連線)')) return;

            try {
                // UI Feedback immediately
                shutdownBtn.disabled = true;
                addMessage('assistant', '🛑 正在關閉系統...');

                await fetch('/shutdown', { method: 'POST' });

                // Keep showing message
                setTimeout(() => {
                    alert('伺服器已關閉，請直接關閉此瀏覽器分頁。');
                    window.close(); // Try to close tab (may be blocked)
                }, 500);

            } catch (err) {
                console.error('Shutdown request failed', err);
                addMessage('assistant', '❌ 關閉失敗，請手動關閉視窗。');
                shutdownBtn.disabled = false;
            }
        });
    }

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

        // 1. Disable Inputs
        userInput.disabled = true;
        sendBtn.disabled = true;

        // Construct UI State object for backend enforcement
        const uiState = {
            hero_hole_cards: heroCards,
            board_cards: boardCards
        };

        try {
            // Capture generation
            const requestGen = currentGeneration;

            const response = await fetch('/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: fullMessage,
                    ui_state: uiState // [NEW] Send structured state
                })
            });

            // Check generation validity
            if (requestGen !== currentGeneration) {
                console.log('Ignore stale response');
                removeMessage(loadingId);
                return;
            }

            const data = await response.json();

            // Remove Loading
            removeMessage(loadingId);

            if (data.error) {
                addMessage('assistant', data.error);
                return;
            }

            // Add Assistant Message
            if (data.advice) {
                addMessage('assistant', formatResponse(data.advice));
            }

            // Update Analysis Panel
            updateAnalysisPanel(data);

            // Sync Visual State (Important for follow-up questions)
            syncVisualState(data.game_state);

            // No need to poll since we got the response synchronously


        } catch (err) {
            removeMessage(loadingId);
            addMessage('assistant', '❌ 發生錯誤，請稍後再試。');
            console.error(err);
        } finally {
            // Re-enable Inputs
            userInput.disabled = false;
            sendBtn.disabled = false;
            setTimeout(() => userInput.focus(), 50); // Restore focus
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
        // 1. Recommendation (Left Side or Top)
        if (strategy && strategy.recommended_action) {
            const amountStr = strategy.amount > 0 ? strategy.amount.toFixed(1) + ' BB' : '';
            const actionLower = strategy.recommended_action.toLowerCase();

            let actionClass = '';
            if (actionLower.includes('raise') || actionLower.includes('all')) actionClass = 'action-raise';
            else if (actionLower.includes('bet')) actionClass = 'action-bet';
            else if (actionLower.includes('call')) actionClass = 'action-call';
            else if (actionLower.includes('check')) actionClass = 'action-check';
            else if (actionLower.includes('fold')) actionClass = 'action-fold';

            html += `
                <div class="strategy-card recommend-card ${actionClass}">
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

    function parseUserMessage(fullText) {
        // Regex to extract cards: "Hero holds AhKh. Board is 7s8d9c. user_text"
        // Also handle cases with only Hero or only Board
        // Try to match standard prefix pattern
        const heroRegex = /Hero holds ([A-Za-z0-9]+)\./;
        const boardRegex = /Board is ([A-Za-z0-9]+)\./;

        let heroCards = [];
        let boardCards = [];
        let cleanText = fullText;

        const heroMatch = fullText.match(heroRegex);
        if (heroMatch) {
            // Split by 2 chars (e.g. AsKs -> [As, Ks])
            // Matches every 2 chars
            heroCards = heroMatch[1].match(/.{1,2}/g) || [];
            cleanText = cleanText.replace(heroMatch[0], '');
        }

        const boardMatch = fullText.match(boardRegex);
        if (boardMatch) {
            boardCards = boardMatch[1].match(/.{1,2}/g) || [];
            cleanText = cleanText.replace(boardMatch[0], '');
        }

        cleanText = cleanText.trim();
        // If empty after trim (only card update), default to update msg
        if (!cleanText) cleanText = "🃏 (更新手牌狀態)";

        return {
            heroCards,
            boardCards,
            cleanText
        };
    }

    async function restoreState() {
        try {
            const res = await fetch('/state');
            if (!res.ok) return;
            const data = await res.json();

            // Store parsed cards from the *latest* user message to handle pending state restoration
            let pendingHeroCards = [];
            let pendingBoardCards = [];

            // 1. Restore Chat History
            let lastMsgRole = null;
            if (data.chat_history && data.chat_history.length > 0) {
                // Clear default greeting/content ONLY if we have history to show
                chatHistory.innerHTML = '';

                // Check if last message is user (Pending state)
                lastMsgRole = data.chat_history[data.chat_history.length - 1].role;

                data.chat_history.forEach(msg => {
                    let content = msg.content;
                    if (msg.role === 'assistant') {
                        content = formatResponse(content);
                    } else {
                        // For user, parse and clean
                        const parsed = parseUserMessage(content);
                        content = parsed.cleanText;

                        // Keep track of latest cards seen in chat
                        if (parsed.heroCards.length > 0) pendingHeroCards = parsed.heroCards;
                        if (parsed.boardCards.length > 0) pendingBoardCards = parsed.boardCards;
                    }
                    addMessage(msg.role, content);
                });
            }

            // 2. Restore Game State (Cards) from Server
            // If server has state, use it.
            if (data.game_state) {
                syncVisualState(data.game_state);
            }

            // 3. Restore Analysis
            if (data.strategy) {
                updateAnalysisPanel({
                    strategy: data.strategy,
                    game_state: data.game_state
                });
            }

            // 4. Check Pending State (If last msg was user, we are waiting for assistant)
            // If we are pending, the server game_state might be STALE (from previous hand).
            // We should force-update the visual slots with the cards found in the pending message.
            if (lastMsgRole === 'user') {
                // Detected pending response

                // FORCE RESTORE CARDS from user message if available
                if (pendingHeroCards.length > 0 || pendingBoardCards.length > 0) {

                    // Construct a temporary state object to reuse syncVisualState
                    const tempState = {
                        hero_hand: pendingHeroCards,
                        board_cards: pendingBoardCards
                    };
                    syncVisualState(tempState);
                }

                const loadingId = addLoadingIndicator();
                startPolling(data.chat_history.length, loadingId);
            }

        } catch (err) {
            console.error('Failed to restore state', err);
        }
    }

    let pollingInterval = null;

    function startPolling(initialCount, loadingId) {
        if (pollingInterval) clearInterval(pollingInterval);

        pollingInterval = setInterval(async () => {
            try {
                const res = await fetch('/state');
                const data = await res.json();

                // If history length increased, or last message changed to assistant
                if (data.chat_history.length > initialCount) {
                    clearInterval(pollingInterval);
                    pollingInterval = null;
                    removeMessage(loadingId);

                    // Verify the new message is assistant
                    const newMsgs = data.chat_history.slice(initialCount);
                    newMsgs.forEach(msg => {
                        if (msg.role === 'assistant') {
                            addMessage('assistant', formatResponse(msg.content));
                        }
                    });

                    // Also update strategy
                    if (data.strategy) {
                        updateAnalysisPanel({
                            strategy: data.strategy,
                            game_state: data.game_state
                        });
                        syncVisualState(data.game_state);
                    }
                }
            } catch (e) {
                console.error('Polling error', e);
            }
        }, 1500); // Poll every 1.5s
    }

    function stopPolling() {
        if (pollingInterval) {
            clearInterval(pollingInterval);
            pollingInterval = null;
        }

        // Safety check for chatHistory
        if (chatHistory) {
            // Remove valid loading indicators
            try {
                const thinkingBubbles = chatHistory.querySelectorAll('.message.assistant .fa-spin');
                thinkingBubbles.forEach(icon => {
                    const bubble = icon.closest('.message');
                    if (bubble) bubble.remove();
                });
            } catch (e) {
                console.error('Error removing bubbles', e);
            }
        }

        // Force unlock inputs (Safety)
        if (userInput) userInput.disabled = false;
        if (sendBtn) sendBtn.disabled = false;
    }

    // Restore on load
    restoreState();
});
