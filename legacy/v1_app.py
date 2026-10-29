import os
import uvicorn
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

app = FastAPI(
    title="Client Portfolio & Property Valuation Engine",
    version="7.0.0",
)


# --- Pydantic Models for API ---
class PropertyLookupRequest(BaseModel):
  query: str  # Property Address
  purchase_price: float
  entity_type: str  # 'personal', 'super', or 'company'


# --- HTML Frontend Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>WealthNexus - Interactive Property Valuation & Profit Tree</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
    <style>
        .node-card {
            cursor: grab;
            user-select: none;
            touch-action: none;
            transition: box-shadow 0.2s ease, border-color 0.2s ease;
        }
        .node-card:active {
            cursor: grabbing;
        }
        .node-card:hover {
            box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
            border-color: #3b82f6;
        }
    </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col font-sans selection:bg-blue-500 selection:text-white">

    <!-- Top Navigation Bar -->
    <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-40 px-6 py-4 flex items-center justify-between">
        <div class="flex items-center space-x-3">
            <div class="bg-blue-600 text-white p-2.5 rounded-xl shadow-lg shadow-blue-500/30">
                <i class="fa-solid fa-house-chimney-user text-lg"></i>
            </div>
            <div>
                <h1 class="font-bold text-lg tracking-tight">WealthNexus <span class="text-blue-400 font-normal">Property Portfolio Engine</span></h1>
                <p class="text-xs text-slate-400">Live Valuation, Entity Transfer & Profit Tracking</p>
            </div>
        </div>
        <div class="flex items-center space-x-3">
            <button onclick="resetPositions()" class="bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs px-3 py-1.5 rounded-lg border border-slate-700 transition-colors">
                <i class="fa-solid fa-rotate-left mr-1"></i> Reset Layout
            </button>
            <span class="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
                <span class="w-1.5 h-1.5 mr-1.5 bg-emerald-400 rounded-full animate-pulse"></span> FastAPI Connected
            </span>
        </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-[1600px] w-full mx-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-8">
        
        <!-- Left Sidebar: Property Ingestion Form -->
        <section class="lg:col-span-4 bg-slate-900/60 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col justify-between">
            <div>
                <div class="flex items-center space-x-2 pb-4 border-b border-slate-800 mb-6">
                    <i class="fa-solid fa-magnifying-glass-location text-blue-400"></i>
                    <h2 class="font-semibold text-base text-slate-200">Add / Lookup Property Address</h2>
                </div>

                <form id="lookupForm" class="space-y-4">
                    <div>
                        <label class="block text-xs font-medium text-slate-400 mb-1">Property Address</label>
                        <input type="text" id="propQuery" required 
                            placeholder="e.g. 15 Ocean St, Point Cook" 
                            class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500 transition-colors">
                    </div>

                    <div class="grid grid-cols-2 gap-4">
                        <div>
                            <label class="block text-xs font-medium text-slate-400 mb-1">Purchase Price ($)</label>
                            <input type="number" id="purchasePrice" required value="750000"
                                class="w-full bg-slate-950 border border-slate-800 rounded-xl px-4 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500 transition-colors">
                        </div>
                        <div>
                            <label class="block text-xs font-medium text-slate-400 mb-1">Holding Entity</label>
                            <select id="entityType" 
                                class="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2.5 text-sm text-slate-200 focus:outline-none focus:border-blue-500 transition-colors">
                                <option value="personal">Personally Owned</option>
                                <option value="super">Family Super Fund</option>
                                <option value="company">ABC Pty Ltd</option>
                            </select>
                        </div>
                    </div>

                    <button type="submit" id="submitBtn"
                        class="w-full mt-2 bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 text-white font-medium py-3 rounded-xl shadow-lg shadow-blue-600/20 transition-all flex items-center justify-center space-x-2">
                        <i class="fa-solid fa-wand-magic-sparkles"></i>
                        <span>Fetch Valuation & Add to Tree</span>
                    </button>
                </form>
            </div>

            <div class="mt-8 bg-slate-950/60 border border-slate-800/80 rounded-xl p-4">
                <h4 class="text-xs font-semibold text-slate-400 uppercase tracking-wider mb-2 flex items-center">
                    <i class="fa-solid fa-arrows-split-up-and-left mr-1.5 text-blue-400"></i> Entity Transfer Feature
                </h4>
                <p class="text-xs text-slate-400 leading-relaxed">
                    You can easily transfer any property between entities using the dropdown on each card, or delete properties as needed.
                </p>
            </div>
        </section>

        <!-- Right Section: Interactive Portfolio Tree Showcase -->
        <section class="lg:col-span-8 bg-slate-900/60 border border-slate-800 rounded-2xl p-6 shadow-xl flex flex-col">
            <div class="flex items-center justify-between pb-4 border-b border-slate-800 mb-6">
                <div>
                    <h2 class="font-semibold text-base text-slate-200">Portfolio Investment & Profit Tree</h2>
                    <p class="text-xs text-slate-400">Drag boxes freely • Transfer entities • Click for audit trail</p>
                </div>
                <div class="flex items-center space-x-2">
                    <span class="text-xs bg-blue-500/10 text-blue-400 border border-blue-500/20 px-3 py-1.5 rounded-lg font-medium">
                        Total Portfolio Equity: <span id="totalEquityDisplay">$1.20M</span>
                    </span>
                </div>
            </div>

            <!-- Draggable Tree Container -->
            <div id="treeContainer" class="flex-1 bg-slate-950/80 border border-slate-800 rounded-xl p-8 relative overflow-auto min-h-[750px]">
                <!-- Dynamically populated via JS -->
            </div>
        </section>

    </main>

    <!-- Source Provenance Audit Modal -->
    <div id="auditModal" class="fixed inset-0 bg-slate-950/80 backdrop-blur-sm z-50 hidden flex items-center justify-center p-4">
        <div class="bg-slate-900 border border-slate-800 rounded-2xl max-w-lg w-full p-6 shadow-2xl relative">
            <button onclick="closeAudit()" class="absolute top-4 right-4 text-slate-400 hover:text-white">
                <i class="fa-solid fa-xmark text-lg"></i>
            </button>
            <div class="flex items-center space-x-3 mb-4">
                <div class="bg-blue-600/20 text-blue-400 p-2.5 rounded-xl">
                    <i class="fa-solid fa-circle-info text-xl"></i>
                </div>
                <div>
                    <h3 id="modalTitle" class="font-bold text-base text-white">Source Provenance Audit</h3>
                    <p class="text-xs text-slate-400">Data verification & compliance trail</p>
                </div>
            </div>
            <div class="space-y-3 bg-slate-950 p-4 rounded-xl border border-slate-800 text-xs text-slate-300">
                <div class="flex justify-between py-1 border-b border-slate-800/60">
                    <span class="text-slate-400">Data Provider:</span>
                    <span id="modalSource" class="font-semibold text-blue-400">RP Data / CoreLogic AVM</span>
                </div>
                <div class="flex justify-between py-1 border-b border-slate-800/60">
                    <span class="text-slate-400">Last Sold Date:</span>
                    <span id="modalSoldDate" class="text-slate-200">14 Mar 2021</span>
                </div>
                <div class="flex justify-between py-1 border-b border-slate-800/60">
                    <span class="text-slate-400">Current Rent:</span>
                    <span id="modalRent" class="text-emerald-400 font-semibold">$550/wk</span>
                </div>
                <div class="flex justify-between py-1 border-b border-slate-800/60">
                    <span class="text-slate-400">Confidence Score:</span>
                    <span class="font-semibold text-emerald-400">High (96.4%)</span>
                </div>
                <div class="pt-2">
                    <span class="text-slate-400 block mb-1">Source Listing URL:</span>
                    <a id="modalLink" href="#" target="_blank" class="text-blue-400 hover:underline truncate block font-mono bg-slate-900 p-2 rounded border border-slate-800">https://www.domain.com.au</a>
                </div>
            </div>
            <div class="mt-6 flex justify-end">
                <button onclick="closeAudit()" class="bg-slate-800 hover:bg-slate-700 text-white px-4 py-2 rounded-xl text-xs font-medium transition-colors">
                    Close Audit Window
                </button>
            </div>
        </div>
    </div>

    <!-- JavaScript Application Logic -->
    <script>
        // Initial portfolio state with exact user specified addresses
        let portfolioState = {
            personal: [
                { name: "10 Coco Cct, Point Cook", purchase: 745000, current: 1020000, soldDate: "02 Oct 2017", rent: "Rent $685/wk", dot: "bg-blue-600", source: "Domain.com.au AVM", url: "https://www.domain.com.au" },
                { name: "16 Littlecroft St, Point Cook", purchase: 1240888, current: 1315000, soldDate: "01 Nov 2024", rent: "Owner Occupied", dot: "bg-blue-600", source: "CoreLogic RP Data", url: "https://www.realestate.com.au" },
                { name: "24 Scatter Road Fraser Rise", purchase: 309500, current: 720000, soldDate: "Oct 2020", rent: "Rent $520/wk", dot: "bg-blue-600", source: "PropTrack API", url: "https://www.domain.com.au" }
            ],
            super: [
                { name: "10 Yarkon Way", purchase: 635000, current: 780000, soldDate: "16 Jan 2022", rent: "Rent $565/wk", dot: "bg-amber-500", source: "Commercial Property Index", url: "https://www.realestate.com.au" }
            ],
            company: [] // ABC Pty Ltd: None
        };

        let nodePositions = {};

        function renderTree() {
            const container = document.getElementById('treeContainer');
            
            // Calculate total equity
            let totalEq = 0;
            Object.values(portfolioState).flat().forEach(h => {
                totalEq += (h.current - h.purchase);
            });
            document.getElementById('totalEquityDisplay').innerText = '$' + (totalEq / 1e6).toFixed(2) + 'M';

            let html = `
            <div id="treeWrapper" class="relative w-full" style="min-width: 1250px; min-height: 800px;">
                <!-- SVG Layer for Dynamic Auto-Sync Curves -->
                <svg id="treeSvg" class="absolute inset-0 w-full h-full pointer-events-none" style="z-index: 1;"></svg>

                <!-- Column 1: YOU Root Node -->
                <div id="card-root" class="absolute cursor-grab" style="left: 40px; top: 280px; width: 160px; z-index: 2;"
                     onmousedown="startDrag(event, 'card-root')" ontouchstart="startDrag(event, 'card-root')">
                    <div onclick="openAudit('YOU', 'Master Portfolio Root', 'Nitin Malhotra', 'N/A', 'N/A', 'https://dash.wealthnexus.com.au')"
                         class="node-card bg-[#1e293b] border-2 border-slate-700 p-4 rounded-2xl shadow-2xl text-center">
                        <div class="text-2xl mb-1">🏠</div>
                        <div class="font-bold text-sm text-white tracking-wide">YOU</div>
                        <div class="text-[10px] text-slate-400 mt-0.5">Master Portfolio</div>
                    </div>
                </div>

                <!-- Column 2: Entities -->
                <div id="card-entity-personal" class="absolute cursor-grab" style="left: 320px; top: 120px; width: 260px; z-index: 2;"
                     onmousedown="startDrag(event, 'card-entity-personal')" ontouchstart="startDrag(event, 'card-entity-personal')">
                    <div onclick="openAudit('personal', 'Personally owned', 'AVM Aggregator Feed', 'N/A', 'N/A', 'https://www.domain.com.au')"
                         class="node-card bg-white text-slate-900 border-l-4 border-blue-500 p-3.5 rounded-xl shadow-lg">
                        <div class="font-bold text-sm text-slate-900">Personally owned</div>
                        <div class="text-xs text-slate-500 mt-0.5">${portfolioState.personal.length} holdings</div>
                    </div>
                </div>

                <div id="card-entity-super" class="absolute cursor-grab" style="left: 320px; top: 420px; width: 260px; z-index: 2;"
                     onmousedown="startDrag(event, 'card-entity-super')" ontouchstart="startDrag(event, 'card-entity-super')">
                    <div onclick="openAudit('super', 'Family Super Fund', 'SMSF Audit Report', 'N/A', 'N/A', 'https://www.ato.gov.au/super')"
                         class="node-card bg-white text-slate-900 border-l-4 border-amber-500 p-3.5 rounded-xl shadow-lg">
                        <div class="font-bold text-sm text-slate-900">Family Super Fund</div>
                        <div class="text-xs text-slate-500 mt-0.5">${portfolioState.super.length} holding</div>
                    </div>
                </div>

                <div id="card-entity-company" class="absolute cursor-grab" style="left: 320px; top: 620px; width: 260px; z-index: 2;"
                     onmousedown="startDrag(event, 'card-entity-company')" ontouchstart="startDrag(event, 'card-entity-company')">
                    <div onclick="openAudit('company', 'ABC Pty Ltd', 'ASIC Registry', 'N/A', 'N/A', 'https://asic.gov.au')"
                         class="node-card bg-white text-slate-900 border-l-4 border-rose-500 p-3.5 rounded-xl shadow-lg">
                        <div class="font-bold text-sm text-slate-900">ABC Pty Ltd</div>
                        <div class="text-xs text-slate-500 mt-0.5">${portfolioState.company.length} holding (None)</div>
                    </div>
                </div>

                <!-- Column 3: Holdings & Properties -->
            `;

            let allGroupedHoldings = [
                { list: 'personal', items: portfolioState.personal, startY: 60 },
                { list: 'super', items: portfolioState.super, startY: 420 },
                { list: 'company', items: portfolioState.company, startY: 620 }
            ];

            allGroupedHoldings.forEach(group => {
                group.items.forEach((h, idx) => {
                    const cardId = `card-holding-${group.list}-${idx}`;
                    const defaultY = group.startY + (idx * 110);
                    const profit = h.current - h.purchase;
                    const margin = h.purchase > 0 ? ((profit / h.purchase) * 100).toFixed(1) : 0;
                    const currStr = `$${(h.current/1e3).toFixed(0)}k`;
                    const purchStr = `$${(h.purchase/1e3).toFixed(0)}k`;
                    
                    const profitStr = profit >= 0 ? `+$${(profit/1e3).toFixed(0)}k (+${margin}%)` : `-$${(Math.abs(profit)/1e3).toFixed(0)}k (${margin}%)`;
                    const profitColor = profit >= 0 ? 'text-emerald-600' : 'text-red-650';

                    let posX = 640;
                    let posY = defaultY;
                    if (nodePositions[cardId]) {
                        posX = nodePositions[cardId].x;
                        posY = nodePositions[cardId].y;
                    }

                    html += `
                        <div id="${cardId}" class="absolute cursor-grab" style="left: ${posX}px; top: ${posY}px; width: 335px; z-index: 2;"
                             onmousedown="startDrag(event, '${cardId}')" ontouchstart="startDrag(event, '${cardId}')">
                            <div class="node-card bg-white text-slate-900 border border-slate-200 p-3 rounded-xl shadow-md">
                                <div class="flex justify-between items-center cursor-pointer" onclick="openAudit('${h.name}', '${h.name}', '${h.source}', '${h.soldDate}', '${h.rent}', '${h.url}')">
                                    <span class="font-bold text-xs text-slate-900 flex items-center truncate">
                                        <span class="w-2 h-2 rounded-full ${h.dot} inline-block mr-1.5 shrink-0"></span>
                                        <span class="truncate">${h.name}</span>
                                    </span>
                                    <span class="text-[10px] text-emerald-600 font-bold shrink-0 ml-1">+${margin}%</span>
                                </div>
                                <div class="text-[11px] text-slate-500 mt-0.5 cursor-pointer" onclick="openAudit('${h.name}', '${h.name}', '${h.source}', '${h.soldDate}', '${h.rent}', '${h.url}')">Val: <b>${currStr}</b> | Bought: ${purchStr}</div>
                                <div class="text-[10px] text-slate-400 mt-0.5 cursor-pointer" onclick="openAudit('${h.name}', '${h.name}', '${h.source}', '${h.soldDate}', '${h.rent}', '${h.url}')">Sold: ${h.soldDate} | ${h.rent}</div>
                                <div class="text-[10px] ${profitColor} font-semibold mt-0.5 cursor-pointer" onclick="openAudit('${h.name}', '${h.name}', '${h.source}', '${h.soldDate}', '${h.rent}', '${h.url}')">Profit: ${profitStr}</div>
                                
                                <!-- Transfer & Remove Controls -->
                                <div class="mt-2 pt-2 border-t border-slate-100 flex items-center justify-between text-[11px]">
                                    <div class="flex items-center space-x-1">
                                        <span class="text-slate-400 text-[10px]">Move to:</span>
                                        <select onchange="transferProperty('${group.list}', ${idx}, this.value)" class="bg-slate-100 text-slate-800 rounded px-1.5 py-0.5 text-[10px] font-medium border border-slate-300 focus:outline-none">
                                            <option value="personal" ${group.list==='personal'?'selected':''}>Personal</option>
                                            <option value="super" ${group.list==='super'?'selected':''}>Super Fund</option>
                                            <option value="company" ${group.list==='company'?'selected':''}>ABC Pty Ltd</option>
                                        </select>
                                    </div>
                                    <button onclick="removeProperty('${group.list}', ${idx})" class="text-red-500 hover:text-red-700 p-1 rounded" title="Remove Property">
                                        <i class="fa-solid fa-trash text-xs"></i>
                                    </button>
                                </div>
                            </div>
                        </div>
                    `;
                });
            });

            html += `</div>`;
            container.innerHTML = html;

            applySavedPositions();
            setTimeout(drawConnectors, 10);
        }

        function transferProperty(fromList, index, targetList) {
            if (fromList === targetList) return;
            const prop = portfolioState[fromList].splice(index, 1)[0];
            // Update dot color based on target entity
            if (targetList === 'personal') prop.dot = 'bg-blue-600';
            else if (targetList === 'super') prop.dot = 'bg-amber-500';
            else if (targetList === 'company') prop.dot = 'bg-rose-500';

            portfolioState[targetList].push(prop);
            nodePositions = {}; // reset card layout offsets on transfer
            renderTree();
        }

        function removeProperty(listKey, index) {
            portfolioState[listKey].splice(index, 1);
            nodePositions = {};
            renderTree();
        }

        function applySavedPositions() {
            ['card-root', 'card-entity-personal', 'card-entity-super', 'card-entity-company'].forEach(id => {
                if (nodePositions[id]) {
                    const el = document.getElementById(id);
                    if (el) {
                        el.style.left = nodePositions[id].x + 'px';
                        el.style.top = nodePositions[id].y + 'px';
                    }
                }
            });
        }

        // --- Drag and Drop Engine ---
        let activeDragId = null;
        let dragStartX = 0;
        let dragStartY = 0;
        let cardStartX = 0;
        let cardStartY = 0;

        function startDrag(e, cardId) {
            if (e.target.tagName === 'A' || e.target.tagName === 'BUTTON' || e.target.tagName === 'SELECT') return;
            
            activeDragId = cardId;
            const el = document.getElementById(cardId);
            el.style.zIndex = 100;

            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;

            dragStartX = clientX;
            dragStartY = clientY;
            cardStartX = el.offsetLeft;
            cardStartY = el.offsetTop;

            document.addEventListener('mousemove', onMouseMove);
            document.addEventListener('mouseup', onMouseUp);
            document.addEventListener('touchmove', onMouseMove);
            document.addEventListener('touchend', onMouseUp);
        }

        function onMouseMove(e) {
            if (!activeDragId) return;
            const el = document.getElementById(activeDragId);
            if (!el) return;

            const clientX = e.touches ? e.touches[0].clientX : e.clientX;
            const clientY = e.touches ? e.touches[0].clientY : e.clientY;

            const dx = clientX - dragStartX;
            const dy = clientY - dragStartY;

            const newX = cardStartX + dx;
            const newY = cardStartY + dy;

            el.style.left = newX + 'px';
            el.style.top = newY + 'px';

            nodePositions[activeDragId] = { x: newX, y: newY };
            drawConnectors();
        }

        function onMouseUp() {
            if (activeDragId) {
                const el = document.getElementById(activeDragId);
                if (el) el.style.zIndex = 2;
            }
            activeDragId = null;
            document.removeEventListener('mousemove', onMouseMove);
            document.removeEventListener('mouseup', onMouseUp);
            document.removeEventListener('touchmove', onMouseMove);
            document.removeEventListener('touchend', onMouseUp);
        }

        function resetPositions() {
            nodePositions = {};
            renderTree();
        }

        function drawConnectors() {
            const wrapper = document.getElementById('treeWrapper');
            const svg = document.getElementById('treeSvg');
            if (!wrapper || !svg) return;

            const wrapperRect = wrapper.getBoundingClientRect();
            let svgContent = '';

            const rootEl = document.getElementById('card-root');
            if (!rootEl) return;
            const rootRect = rootEl.getBoundingClientRect();
            const rootX = rootRect.right - wrapperRect.left;
            const rootY = rootRect.top + (rootRect.height / 2) - wrapperRect.top;

            const entities = [
                { key: 'personal', color: '#3b82f6' },
                { key: 'super', color: '#f59e0b' },
                { key: 'company', color: '#ef4444' }
            ];

            entities.forEach(ent => {
                const entEl = document.getElementById(`card-entity-${ent.key}`);
                if (!entEl) return;
                const entRect = entEl.getBoundingClientRect();
                const entX = entRect.left - wrapperRect.left;
                const entY = entRect.top + (entRect.height / 2) - wrapperRect.top;

                svgContent += `<path d="M ${rootX} ${rootY} C ${rootX + 60} ${rootY}, ${entX - 60} ${entY}, ${entX} ${entY}" fill="none" stroke="${ent.color}" stroke-width="2.5" />`;

                const items = portfolioState[ent.key];
                items.forEach((_, idx) => {
                    const holdingEl = document.getElementById(`card-holding-${ent.key}-${idx}`);
                    if (!holdingEl) return;
                    const holdRect = holdingEl.getBoundingClientRect();
                    const holdX = holdRect.left - wrapperRect.left;
                    const holdY = holdRect.top + (holdRect.height / 2) - wrapperRect.top;
                    const entRightX = entRect.right - wrapperRect.left;

                    svgContent += `<path d="M ${entRightX} ${entY} C ${entRightX + 50} ${entY}, ${holdX - 50} ${holdY}, ${holdX} ${holdY}" fill="none" stroke="${ent.color}" stroke-width="2" />`;
                });
            });

            svg.innerHTML = svgContent;
        }

        function openAudit(title, subtitle, sourceName, soldDate, rent, url) {
            document.getElementById('modalTitle').innerText = title;
            document.getElementById('modalSource').innerText = sourceName;
            document.getElementById('modalSoldDate').innerText = soldDate;
            document.getElementById('modalRent').innerText = rent;
            const linkEl = document.getElementById('modalLink');
            linkEl.href = url;
            linkEl.innerText = url;
            document.getElementById('auditModal').classList.remove('hidden');
        }

        function closeAudit() {
            document.getElementById('auditModal').classList.add('hidden');
        }

        // Handle Property Form Ingestion
        document.getElementById('lookupForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const btn = document.getElementById('submitBtn');
            btn.innerHTML = '<i class="fa-solid fa-spinner animate-spin"></i><span>Querying Domain API & AVM...</span>';
            
            const payload = {
                query: document.getElementById('propQuery').value,
                purchase_price: parseFloat(document.getElementById('purchasePrice').value),
                entity_type: document.getElementById('entityType').value
            };

            try {
                const response = await fetch('/api/lookup-valuation', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await response.json();
                
                let dotColor = 'bg-blue-600';
                if (data.entity === 'super') dotColor = 'bg-amber-500';
                if (data.entity === 'company') dotColor = 'bg-rose-500';

                portfolioState[data.entity].push({
                    name: data.address,
                    purchase: data.purchase_price,
                    current: data.current_value,
                    soldDate: data.last_sold_date,
                    rent: data.current_rent,
                    dot: dotColor,
                    source: data.provenance_source,
                    url: data.source_url
                });

                renderTree();
                document.getElementById('lookupForm').reset();
            } catch (err) {
                console.error(err);
                alert('Error connecting to backend valuation API.');
            } finally {
                btn.innerHTML = '<i class="fa-solid fa-wand-magic-sparkles"></i><span>Fetch Valuation & Add to Tree</span>';
            }
        });

        window.onload = renderTree;
        window.onresize = drawConnectors;
    </script>
</body>
</html>
"""


# --- FastAPI Routes ---
@app.get("/", response_class=HTMLResponse)
def serve_frontend():
  return HTML_TEMPLATE


@app.post("/api/lookup-valuation")
def lookup_valuation(data: PropertyLookupRequest):
  """FastAPI backend endpoint that simulates fetching valuation data,

  last sold date, and current rent from Domain.com.au / CoreLogic.
  """
  purchase = data.purchase_price
  estimated_current_value = round(purchase * 1.25, -2)
  profit = estimated_current_value - purchase
  margin_pct = round((profit / purchase) * 100, 1)

  return {
      "status": "success",
      "address": data.query,
      "entity": data.entity_type,
      "purchase_price": purchase,
      "current_value": estimated_current_value,
      "profit": profit,
      "profit_margin_pct": margin_pct,
      "last_sold_date": "15 Oct 2022",
      "current_rent": "Rent $580/wk",
      "provenance_source": "Domain.com.au AVM & CoreLogic RP Data",
      "source_url": f"https://www.domain.com.au/property-profile/{data.query.lower().replace(' ', '-')}",
  }


if __name__ == "__main__":
  print(
      "Starting FastAPI Server... Open http://127.0.0.1:8000 in your browser."
  )
  uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=True)