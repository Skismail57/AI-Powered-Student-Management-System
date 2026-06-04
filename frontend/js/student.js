
const API_BASE = 'http://localhost:5000';
const socket = io(API_BASE);
let attendanceChart, performanceChart;

async function authedGet(path) {
    const response = await fetch(`${API_BASE}${path}`, {
        headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
    });
    if (response.status === 401) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = 'login.html';
        return;
    }
    return await response.json();
}

document.addEventListener('DOMContentLoaded', () => {
    const user = JSON.parse(localStorage.getItem('user'));
    const token = localStorage.getItem('token');
    
    if (!token || user.role !== 'student') {
        window.location.href = 'login.html';
        return;
    }

    // Dynamic Role-Based Theme
    const body = document.body;
    if (user.dept_name) {
        const dept = user.dept_name.toLowerCase();
        if (dept.includes('computer') || dept.includes('engineering') || dept.includes('cse')) {
            body.setAttribute('data-role', 'student-cse');
        } else if (dept.includes('medical') || dept.includes('mbbs') || dept.includes('anatomy')) {
            body.setAttribute('data-role', 'student-medical');
        }
    }

    document.getElementById('studentName').textContent = user.name;

    document.getElementById('logoutBtn').addEventListener('click', () => {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = 'login.html';
    });

    // Load initial data
    loadDashboard();
    loadGamification();
    initTheme();
    
    // Socket listeners
    socket.on('dashboard_update', loadDashboard);
    socket.on('gamification_update', loadGamification);
});

function showSection(sectionId) {
    // Hide all sections
    const sections = document.querySelectorAll('.content-section');
    sections.forEach(section => {
        section.classList.add('hidden');
        section.classList.remove('fade-in');
    });

    // Show selected section
    const selectedSection = document.getElementById(sectionId);
    if (selectedSection) {
        selectedSection.classList.remove('hidden');
        selectedSection.classList.add('fade-in');
    }

    // Update sidebar active state
    const sidebarItems = document.querySelectorAll('.sidebar-item');
    sidebarItems.forEach(item => {
        item.classList.remove('active');
    });
    
    // Handle active state
    const activeLink = document.querySelector(`a[onclick="showSection('${sectionId}')"]`);
    if (activeLink) {
        activeLink.classList.add('active');
    }

    // Load section specific data
    if (sectionId === 'dashboard') loadDashboard();
    if (sectionId === 'curriculum') loadCurriculum();
    if (sectionId === 'learning') resetLearningBrowse();
    if (sectionId === 'academic-calendar') loadAcademicCalendar();
    if (sectionId === 'timetable') loadTimetable();
    if (sectionId === 'leaderboard') loadLeaderboard();
    if (sectionId === 'notices') loadNotices();
    if (sectionId === 'social-feed') loadSocialFeed();
    if (sectionId === 'library') loadLibraryBooks();
    if (sectionId === 'placement') loadPlacementJobs();
    if (sectionId === 'campus') loadCampusServices();
    if (sectionId === 'forum') loadForumTopics();
    if (sectionId === 'faculty') loadFacultyProfiles();
    if (sectionId === 'exams') loadMockTests();
    if (sectionId === 'planner') loadAcademicGoals();
    if (sectionId === 'cgpa') loadGpaTracker();
    if (sectionId === 'resume') loadResumeData();
    if (sectionId === 'cafeteria') loadCafeteriaMenu();
    if (sectionId === 'health') loadHealthRecords();
    if (sectionId === 'parking') loadParkingSlots();
    if (sectionId === 'streaming') loadLiveEvents();
    if (sectionId === 'learning') {
        resetLearningBrowse();
        loadBengaluruColleges();
    }
}

// BENGALURU COLLEGES & FACULTY
async function loadBengaluruColleges() {
    try {
        const res = await fetch(`${API_BASE}/institutions/detailed`);
        const data = await res.json();
        const grid = document.getElementById('bengaluruCollegeGrid');
        if (!grid) return;

        grid.innerHTML = data.items.map(inst => `
            <div class="bg-gray-50 p-4 rounded-xl border hover:border-indigo-300 transition group">
                <img src="${inst.image_url || 'https://images.unsplash.com/photo-1562774053-701939374585?auto=format&fit=crop&w=400&q=80'}" class="w-full h-32 object-cover rounded-lg mb-3">
                <h4 class="font-bold text-gray-800 group-hover:text-indigo-600">${inst.name}</h4>
                <p class="text-[10px] text-gray-500 uppercase font-bold mb-2">${inst.type}</p>
                <div class="flex flex-wrap gap-1">
                    ${inst.departments.slice(0, 3).map(d => `<span class="text-[9px] bg-white px-1.5 py-0.5 rounded border text-gray-400">${d.name}</span>`).join('')}
                    ${inst.departments.length > 3 ? `<span class="text-[9px] text-gray-400">+${inst.departments.length - 3} more</span>` : ''}
                </div>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-8 col-span-full">No college data available.</p>';
    } catch (err) { console.error(err); }
}

async function loadFacultyProfiles() {
    try {
        const res = await fetch(`${API_BASE}/faculty/profiles`);
        const data = await res.json();
        const grid = document.getElementById('facultyProfilesGrid');
        if (!grid) return;

        grid.innerHTML = data.items.map(f => `
            <div class="bg-white p-6 rounded-2xl shadow-sm border hover:shadow-md transition">
                <div class="flex items-center space-x-4 mb-6">
                    <img src="${f.image_url || 'https://images.unsplash.com/photo-1537368910025-700350fe46c7?auto=format&fit=crop&w=150&q=80'}" class="w-16 h-16 rounded-full object-cover border-2 border-indigo-100">
                    <div>
                        <h4 class="font-bold text-gray-800">${f.faculty_name}</h4>
                        <p class="text-xs text-indigo-600 font-bold">${f.designation}</p>
                        <p class="text-[10px] text-gray-400 uppercase tracking-widest">${f.department_name || 'General'}</p>
                    </div>
                </div>
                <div class="space-y-3">
                    <div>
                        <p class="text-[10px] font-bold text-gray-400 uppercase">Specialization</p>
                        <p class="text-sm text-gray-700">${f.specialization || 'Academic Excellence'}</p>
                    </div>
                    <div>
                        <p class="text-[10px] font-bold text-gray-400 uppercase">Biography</p>
                        <p class="text-xs text-gray-500 leading-relaxed line-clamp-3">${f.bio || 'Dedicated educator committed to student success and academic research.'}</p>
                    </div>
                </div>
                <button class="w-full mt-6 py-2 rounded-lg bg-indigo-50 text-indigo-600 text-xs font-bold hover:bg-indigo-600 hover:text-white transition">
                    View Publications
                </button>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-12 col-span-full">Faculty data coming soon.</p>';
    } catch (err) { console.error(err); }
}

// GAMIFICATION
async function loadGamification() {
    try {
        const data = await authedGet('/student/gamification');
        const statusEl = document.getElementById('gamificationStatus');
        if (!data || !statusEl) return;
        
        statusEl.classList.remove('hidden');
        document.getElementById('studentLevel').textContent = data.level;
        document.getElementById('studentXP').textContent = data.xp;
        
        const currentLevelXP = data.xp % 100;
        const percent = currentLevelXP; // Level up every 100 XP
        document.getElementById('xpBar').style.width = `${percent}%`;
    } catch (err) { console.error(err); }
}

// CURRICULUM & OBE (master data + GPA)
async function loadCurriculum() {
    const sem = document.getElementById('curriculumSemFilter').value;
    const grid = document.getElementById('curriculumGrid');
    const gpaBar = document.getElementById('curriculumGpaBar');
    try {
        const response = await fetch(`${API_BASE}/academic/curriculum?semester=${sem}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        if (data.gpa && gpaBar) {
            gpaBar.classList.remove('hidden');
            document.getElementById('curriculumCgpa').textContent = data.gpa.cgpa != null ? data.gpa.cgpa : 'N/A';
            document.getElementById('curriculumCredits').textContent = data.gpa.credits_earned ?? 0;
            document.getElementById('curriculumBacklogs').textContent = data.gpa.backlogs ?? 0;
        }
        const items = data.items || [];
        grid.innerHTML = items.map(sub => {
            const grade = sub.grade || {};
            const status = grade.status || 'pending';
            const gp = grade.grade_points != null ? `GP ${grade.grade_points}` : 'Not graded';
            const statusCls = status === 'passed' ? 'text-emerald-600' : status === 'backlog' || status === 'failed' ? 'text-rose-600' : 'text-gray-500';
            const masterId = sub.source === 'master' ? sub.id : null;
            const clickId = masterId || sub.id;
            const clickHandler = masterId
                ? `loadOBE(${sub.id}, true)`
                : `loadOBE(${sub.id}, false)`;
            return `
            <div onclick="${clickHandler}" class="bg-white p-4 rounded-lg shadow-sm border hover:border-indigo-500 transition cursor-pointer">
                <div class="flex justify-between items-start gap-2">
                    <div>
                        <p class="text-[10px] font-mono text-gray-400">${sub.code || ''} · ${sub.department_name || 'Dept'}</p>
                        <h4 class="font-bold text-gray-800">${sub.subject_name}</h4>
                        <p class="text-xs text-gray-500">${sub.credits} credits · ${sub.material_count || 0} materials</p>
                        ${sub.syllabus ? `<p class="text-xs text-gray-400 mt-1 line-clamp-2">${sub.syllabus}</p>` : ''}
                    </div>
                    <div class="text-right shrink-0">
                        <p class="text-xs font-bold ${statusCls}">${status.toUpperCase()}</p>
                        <p class="text-[10px] text-gray-500">${gp}</p>
                    </div>
                </div>
            </div>`;
        }).join('') || '<p class="text-center text-gray-500 py-8">No subjects in master catalog for this semester. Ask admin to add subjects in Master Data.</p>';
    } catch (err) {
        console.error(err);
        if (grid) grid.innerHTML = '<p class="text-red-500 text-sm">Failed to load curriculum.</p>';
    }
}

async function loadOBE(subjectId, isMaster = false) {
    try {
        const qs = isMaster
            ? `master_subject_id=${subjectId}`
            : `subject_id=${subjectId}`;
        const response = await fetch(`${API_BASE}/academic/obe?${qs}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('obeOutcomesList');
        if (!data.items || data.items.length === 0) {
            list.innerHTML = '<p class="text-gray-500 text-sm italic">No CO/PO outcomes mapped yet for this subject.</p>';
            return;
        }
        list.innerHTML = data.items.map(o => `
            <div class="p-3 bg-gray-50 rounded border">
                <div class="flex justify-between mb-1">
                    <span class="text-[10px] font-bold text-indigo-600 uppercase">${o.outcome_type} ${o.outcome_code}</span>
                    <span class="text-[10px] font-bold text-gray-400">Target: ${o.target_attainment}%</span>
                </div>
                <p class="text-xs text-gray-700">${o.description}</p>
            </div>
        `).join('');
    } catch (err) { console.error(err); }
}

async function loadGpaTracker() {
    try {
        const [gpaData, predictData] = await Promise.all([
            authedGet('/academic/gpa/me'),
            fetch(`${API_BASE}/cgpa/predict`, { headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` } }).then(r => r.json())
        ]);
        const recordedEl = document.getElementById('recordedCgpaVal');
        if (recordedEl) recordedEl.textContent = gpaData?.cgpa != null ? gpaData.cgpa : 'N/A';
        const creditsEl = document.getElementById('gpaCreditsEarned');
        if (creditsEl) creditsEl.textContent = gpaData?.credits_earned ?? 0;
        const backlogEl = document.getElementById('gpaBacklogCount');
        if (backlogEl) backlogEl.textContent = gpaData?.backlogs ?? 0;
        const list = document.getElementById('gpaGradesList');
        const grades = gpaData?.grades || [];
        if (list) {
            list.innerHTML = grades.length ? grades.map(g => `
                <div class="flex justify-between p-3 rounded border bg-gray-50">
                    <div>
                        <p class="font-semibold">${g.subject_name}</p>
                        <p class="text-xs text-gray-500">${g.subject_code || ''} · ${g.credits} cr</p>
                    </div>
                    <div class="text-right">
                        <p class="font-bold">${g.grade_points != null ? g.grade_points : '--'}</p>
                        <p class="text-xs uppercase ${g.status === 'passed' ? 'text-emerald-600' : 'text-rose-600'}">${g.status}</p>
                    </div>
                </div>
            `).join('') : '<p class="text-gray-500">No graded subjects yet. Faculty will record marks here.</p>';
        }
        if (predictData?.predicted_cgpa != null) {
            document.getElementById('predictedCgpaVal').textContent = predictData.predicted_cgpa;
            const f = predictData.factors || {};
            document.getElementById('cgpaFeedback').textContent =
                `Based on attendance ${f.attendance}%, study ${f.study_hours}h, sleep ${f.sleep_hours}h.`;
        }
    } catch (err) {
        console.error(err);
    }
}

// TIMETABLE
async function loadTimetable() {
    const user = JSON.parse(localStorage.getItem('user'));
    const sem = user.semester_id || 1;
    const deptId = user.dept_id || 1;
    
    try {
        const response = await fetch(`${API_BASE}/api/timetable/${deptId}/${sem}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const tbody = document.getElementById('timetableBody');
        
        const days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'];
        tbody.innerHTML = days.map(day => {
            const daySlots = data.items.filter(i => i.day_of_week === day);
            return `
                <tr class="hover:bg-gray-50">
                    <td class="p-4 border-b font-bold text-gray-600 bg-gray-50">${day}</td>
                    ${[1, 2, 'lunch', 3, 4].map(slot => {
                        if (slot === 'lunch') return '<td class="p-4 border-b text-center text-gray-400 italic bg-gray-50">Lunch Break</td>';
                        
                        const slotIdx = slot > 2 ? slot - 2 : slot - 1;
                        const item = daySlots[slotIdx];
                        return `
                            <td class="p-4 border-b text-center">
                                ${item ? `
                                    <div class="text-xs font-bold text-indigo-600">${item.subject_name}</div>
                                    <div class="text-[9px] text-gray-400">${item.room_number || 'Room TBD'}</div>
                                ` : '<span class="text-gray-200">-</span>'}
                            </td>
                        `;
                    }).join('')}
                </tr>
            `;
        }).join('');
    } catch (err) { console.error(err); }
}

async function loadLeaderboard() {
    try {
        const response = await fetch(`${API_BASE}/student/leaderboard`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const tbody = document.getElementById('leaderboardBody');
        
        tbody.innerHTML = data.items.map((s, i) => `
            <tr class="hover:bg-gray-50 border-b">
                <td class="p-4 font-bold text-gray-500">#${i + 1}</td>
                <td class="p-4">
                    <div class="flex items-center space-x-3">
                        <img src="https://picsum.photos/seed/${s.student_id}/32/32" class="w-8 h-8 rounded-full">
                        <span class="font-bold text-gray-800">${s.student_name}</span>
                    </div>
                </td>
                <td class="p-4 text-right"><span class="bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full text-xs font-bold">Lvl ${s.level}</span></td>
                <td class="p-4 text-right font-bold text-indigo-600">${s.xp} XP</td>
            </tr>
        `).join('') || '<p class="text-center py-8">No data available.</p>';
    } catch (err) { console.error(err); }
}

async function loadNotices() {
    try {
        const response = await fetch(`${API_BASE}/campus/notices`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('noticesList');
        
        list.innerHTML = data.items.map(notice => `
            <div class="bg-white p-6 rounded-xl shadow-sm border-l-4 border-amber-500">
                <div class="flex justify-between items-start mb-4">
                    <h4 class="font-bold text-lg text-gray-800">${notice.title}</h4>
                    <span class="bg-amber-100 text-amber-700 text-[10px] font-bold px-2 py-1 rounded uppercase">
                        ${notice.target_role === 'all' ? 'Universal' : 'Targeted'}
                    </span>
                </div>
                <p class="text-sm text-gray-600 leading-relaxed mb-4">${notice.content}</p>
                <div class="text-[10px] text-gray-400 font-bold uppercase tracking-wider">
                    Posted: ${new Date(notice.created_at).toLocaleDateString()}
                </div>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-12 col-span-full">No active notices.</p>';
    } catch (err) { console.error(err); }
}

// CAMPUS SOCIAL FEED
async function loadSocialFeed() {
    try {
        const response = await fetch(`${API_BASE}/campus/social-feed`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('socialFeedList');
        
        list.innerHTML = data.items.map(post => `
            <div class="bg-white p-6 rounded-xl shadow-sm border">
                <div class="flex items-center space-x-3 mb-4">
                    <img src="https://picsum.photos/seed/${post.author_id}/40/40" class="w-10 h-10 rounded-full">
                    <div>
                        <p class="text-sm font-bold text-gray-800">${post.author_role === 'student' ? 'Student' : 'Faculty Member'}</p>
                        <p class="text-[10px] text-gray-400 uppercase font-bold tracking-widest">${new Date(post.created_at).toLocaleString()}</p>
                    </div>
                </div>
                <p class="text-gray-700 leading-relaxed">${post.content}</p>
                ${post.media_url ? `<img src="${post.media_url}" class="mt-4 rounded-lg w-full h-48 object-cover border">` : ''}
                <div class="mt-6 flex items-center space-x-6 border-t pt-4 text-gray-500">
                    <button class="text-sm hover:text-indigo-600 transition">
                        <i class="far fa-heart mr-2"></i> ${post.likes_count} Likes
                    </button>
                    <button class="text-sm hover:text-indigo-600 transition">
                        <i class="far fa-comment mr-2"></i> Comment
                    </button>
                </div>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-12">The campus is quiet today. Be the first to post!</p>';
    } catch (err) { console.error(err); }
}

async function submitSocialPost() {
    const content = document.getElementById('socialPostContent').value;
    if (!content) return showToast('Post content cannot be empty', 'error');

    try {
        const response = await fetch(`${API_BASE}/campus/social-feed`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content })
        });
        if (response.ok) {
            showToast('Update posted! +10 XP', 'success');
            document.getElementById('socialPostContent').value = '';
            loadSocialFeed();
            loadGamification();
        }
    } catch (err) { console.error(err); }
}

// AI ADVISOR
async function sendAIChatMessage() {
    const input = document.getElementById('aiChatInput');
    const query = input.value.trim();
    if (!query) return;

    const messages = document.getElementById('aiChatMessages');
    
    // Add user message
    messages.innerHTML += `
        <div class="flex items-start justify-end space-x-3">
            <div class="bg-indigo-600 text-white p-3 rounded-lg shadow-sm text-sm max-w-[80%]">
                ${query}
            </div>
            <div class="w-8 h-8 bg-gray-200 rounded-full flex items-center justify-center text-gray-500 flex-shrink-0">
                <i class="fas fa-user text-xs"></i>
            </div>
        </div>
    `;
    
    input.value = '';
    messages.scrollTop = messages.scrollHeight;

    // Show typing
    const typingId = 'typing-' + Date.now();
    messages.innerHTML += `
        <div id="${typingId}" class="flex items-start space-x-3">
            <div class="w-8 h-8 bg-indigo-600 rounded-full flex items-center justify-center text-white flex-shrink-0">
                <i class="fas fa-robot text-xs"></i>
            </div>
            <div class="bg-white p-3 rounded-lg shadow-sm border text-sm text-gray-400">
                Thinking...
            </div>
        </div>
    `;
    messages.scrollTop = messages.scrollHeight;

    try {
        const response = await fetch(`${API_BASE}/ai/advisor`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ query })
        });
        const data = await response.json();
        
        document.getElementById(typingId).remove();
        
        messages.innerHTML += `
            <div class="flex items-start space-x-3">
                <div class="w-8 h-8 bg-indigo-600 rounded-full flex items-center justify-center text-white flex-shrink-0">
                    <i class="fas fa-robot text-xs"></i>
                </div>
                <div class="bg-white p-3 rounded-lg shadow-sm border text-sm text-gray-700 max-w-[80%]">
                    ${data.response}
                </div>
            </div>
        `;
        messages.scrollTop = messages.scrollHeight;
    } catch (err) {
        console.error(err);
        if (document.getElementById(typingId)) document.getElementById(typingId).remove();
        showToast('AI connection failed', 'error');
    }
}

// Add enter key support for AI chat
document.addEventListener('DOMContentLoaded', () => {
    const aiInput = document.getElementById('aiChatInput');
    if (aiInput) {
        aiInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') sendAIChatMessage();
        });
    }
});

// CAFETERIA SYSTEM
let cafeteriaCart = [];

async function loadCafeteriaMenu() {
    try {
        const response = await fetch(`${API_BASE}/cafeteria/menu`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const grid = document.getElementById('cafeteriaMenuGrid');
        
        grid.innerHTML = data.items.map(item => `
            <div class="bg-white p-4 rounded-lg shadow-sm border hover:border-indigo-300 transition">
                <div class="h-32 bg-gray-100 rounded mb-4 flex items-center justify-center">
                    <i class="fas fa-hamburger text-4xl text-gray-300"></i>
                </div>
                <div class="flex justify-between items-start mb-2">
                    <h4 class="font-bold text-gray-800">${item.item_name}</h4>
                    <span class="text-indigo-600 font-bold">₹${item.price}</span>
                </div>
                <p class="text-xs text-gray-500 mb-4">${item.category}</p>
                <button onclick="addToCafeteriaCart(${item.id}, '${item.item_name}', ${item.price})" 
                        class="w-full py-2 rounded bg-indigo-50 text-indigo-600 text-xs font-bold hover:bg-indigo-600 hover:text-white transition">
                    Add to Cart
                </button>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-8 col-span-full">Cafeteria is currently closed.</p>';
        
        updateCafeteriaCartUI();
    } catch (err) { console.error(err); }
}

function addToCafeteriaCart(id, name, price) {
    const existing = cafeteriaCart.find(i => i.id === id);
    if (existing) {
        existing.qty++;
    } else {
        cafeteriaCart.push({ id, name, price, qty: 1 });
    }
    updateCafeteriaCartUI();
    showToast(`${name} added to cart`, 'success');
}

function updateCafeteriaCartUI() {
    const list = document.getElementById('cartItems');
    const count = document.getElementById('cartCount');
    const total = document.getElementById('cartTotal');
    
    if (cafeteriaCart.length === 0) {
        list.innerHTML = '<p class="text-gray-500 text-sm">Cart is empty</p>';
        count.textContent = '0';
        total.textContent = '0';
        return;
    }

    list.innerHTML = cafeteriaCart.map(item => `
        <div class="flex justify-between items-center text-sm">
            <div class="flex-1">
                <p class="font-bold text-gray-800">${item.name}</p>
                <p class="text-xs text-gray-500">₹${item.price} x ${item.qty}</p>
            </div>
            <div class="flex items-center gap-2">
                <button onclick="removeFromCafeteriaCart(${item.id})" class="text-gray-400 hover:text-red-500">
                    <i class="fas fa-minus-circle"></i>
                </button>
                <span class="font-bold">${item.qty}</span>
                <button onclick="addToCafeteriaCart(${item.id}, '${item.name}', ${item.price})" class="text-gray-400 hover:text-indigo-500">
                    <i class="fas fa-plus-circle"></i>
                </button>
            </div>
        </div>
    `).join('');

    const totalVal = cafeteriaCart.reduce((sum, i) => sum + (i.price * i.qty), 0);
    const countVal = cafeteriaCart.reduce((sum, i) => sum + i.qty, 0);
    
    count.textContent = countVal;
    total.textContent = totalVal;
}

function removeFromCafeteriaCart(id) {
    const idx = cafeteriaCart.findIndex(i => i.id === id);
    if (idx > -1) {
        if (cafeteriaCart[idx].qty > 1) {
            cafeteriaCart[idx].qty--;
        } else {
            cafeteriaCart.splice(idx, 1);
        }
    }
    updateCafeteriaCartUI();
}

async function placeCafeteriaOrder() {
    if (cafeteriaCart.length === 0) return showToast('Cart is empty', 'error');
    
    const total_price = cafeteriaCart.reduce((sum, i) => sum + (i.price * i.qty), 0);

    try {
        const response = await fetch(`${API_BASE}/cafeteria/order`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ items: cafeteriaCart, total_price })
        });
        if (response.ok) {
            showToast('Order placed! Collect from counter.', 'success');
            cafeteriaCart = [];
            updateCafeteriaCartUI();
        }
    } catch (err) { console.error(err); }
}

// HEALTH RECORDS
async function loadHealthRecords() {
    try {
        const data = await authedGet('/student/health');
        if (data) {
            document.getElementById('healthBloodGroup').value = data.blood_group || '';
            document.getElementById('healthAllergies').value = data.allergies || '';
            document.getElementById('healthHistory').value = data.medical_history || '';
            document.getElementById('healthEmergencyName').value = data.emergency_contact_name || '';
            document.getElementById('healthEmergencyPhone').value = data.emergency_contact_phone || '';
        }
    } catch (err) { console.error(err); }
}

async function saveHealthRecords() {
    const payload = {
        blood_group: document.getElementById('healthBloodGroup').value,
        allergies: document.getElementById('healthAllergies').value,
        medical_history: document.getElementById('healthHistory').value,
        emergency_contact_name: document.getElementById('healthEmergencyName').value,
        emergency_contact_phone: document.getElementById('healthEmergencyPhone').value
    };

    try {
        const response = await fetch(`${API_BASE}/student/health`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            showToast('Health records updated!', 'success');
        }
    } catch (err) { console.error(err); }
}

// WELLNESS TRACKER
async function loadWellness() {
    try {
        const data = await authedGet('/student/wellness');
        // Update charts or list if needed
    } catch (err) { console.error(err); }
}

async function saveWellness(sleep, stress, focus) {
    try {
        const response = await fetch(`${API_BASE}/student/wellness`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ sleep_hours: sleep, stress_level: stress, focus_score: focus })
        });
        if (response.ok) {
            showToast('Wellness log saved!', 'success');
        }
    } catch (err) { console.error(err); }
}

// ADVANCED ACADEMIC (Lectures & Flashcards)
async function loadLectures(subjectId) {
    try {
        const data = await authedGet(`/academic/lectures?subject_id=${subjectId}`);
        // Render lectures
    } catch (err) { console.error(err); }
}

async function loadFlashcards(subjectId) {
    try {
        const data = await authedGet(`/academic/flashcards?subject_id=${subjectId}`);
        // Render flashcards
    } catch (err) { console.error(err); }
}

// PLACEMENT ADVANCED
async function loadMockInterviews() {
    try {
        const data = await authedGet('/placement/mock-interviews');
        const list = document.getElementById('placementInterviewsList');
        if (!list) return;
        list.innerHTML = data.items.map(m => `
            <div class="p-3 bg-gray-50 rounded border">
                <div class="flex justify-between">
                    <span class="font-bold">${m.interviewer_name || 'TBD'}</span>
                    <span class="text-[10px] uppercase font-bold text-indigo-600">${m.status}</span>
                </div>
                <p class="text-xs text-gray-500">${new Date(m.scheduled_at).toLocaleString()}</p>
                ${m.feedback ? `<p class="text-[10px] text-gray-400 mt-1 italic">"${m.feedback}"</p>` : ''}
            </div>
        `).join('') || '<p class="text-xs text-gray-500">No interviews scheduled.</p>';
    } catch (err) { console.error(err); }
}

// CAMPUS ADVANCED
async function loadStudyGroups() {
    try {
        const data = await authedGet('/campus/study-groups');
        // Render groups
    } catch (err) { console.error(err); }
}

// PARKING
async function loadParkingSlots() {
    try {
        const data = await authedGet('/campus/parking/slots');
        const grid = document.getElementById('parkingSlotsGrid');
        if (!grid) return;
        
        grid.innerHTML = data.items.map(slot => `
            <div class="bg-white p-4 rounded-xl border shadow-sm text-center">
                <div class="text-3xl mb-2 ${slot.status === 'available' ? 'text-emerald-500' : 'text-rose-500'}">
                    <i class="fas fa-parking"></i>
                </div>
                <p class="font-bold text-gray-800">${slot.slot_number}</p>
                <p class="text-[10px] text-gray-400 uppercase font-bold">${slot.zone}</p>
                <span class="inline-block mt-2 px-2 py-0.5 rounded text-[10px] font-bold uppercase ${
                    slot.status === 'available' ? 'bg-emerald-100 text-emerald-700' : 'bg-rose-100 text-rose-700'
                }">${slot.status}</span>
            </div>
        `).join('');
    } catch (err) { console.error(err); }
}

async function registerVehicle() {
    const payload = {
        vehicle_number: document.getElementById('vehicleNumber').value,
        vehicle_type: document.getElementById('vehicleType').value
    };

    if (!payload.vehicle_number) return showToast('Vehicle number is required', 'error');

    try {
        const response = await fetch(`${API_BASE}/campus/parking/register`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            showToast('Vehicle registered!', 'success');
            closeModal('registerVehicleModal');
        } else {
            const data = await response.json();
            showToast(data.message, 'error');
        }
    } catch (err) { console.error(err); }
}

// LIVE EVENTS & STREAMING
async function loadLiveEvents() {
    try {
        const data = await authedGet('/campus/events/live');
        const grid = document.getElementById('liveEventsGrid');
        if (!grid) return;
        
        grid.innerHTML = data.items.map(event => `
            <div class="bg-white rounded-2xl shadow-sm border overflow-hidden flex flex-col md:flex-row">
                <div class="md:w-48 h-48 bg-indigo-600 flex items-center justify-center text-white text-4xl">
                    <i class="fas ${event.is_live ? 'fa-broadcast-tower' : 'fa-calendar-alt'}"></i>
                </div>
                <div class="p-6 flex-1">
                    <div class="flex justify-between items-start mb-2">
                        <h4 class="font-bold text-xl text-gray-800">${event.title}</h4>
                        ${event.is_live ? '<span class="px-2 py-1 bg-rose-600 text-white text-[10px] font-bold rounded animate-pulse">LIVE</span>' : ''}
                    </div>
                    <p class="text-sm text-gray-500 mb-4">${event.description}</p>
                    <div class="flex items-center justify-between mt-auto">
                        <span class="text-xs text-gray-400 font-bold">${new Date(event.event_date).toLocaleString()}</span>
                        <a href="${event.stream_url || '#'}" target="_blank" class="px-4 py-2 bg-indigo-50 text-indigo-600 rounded-lg text-xs font-bold hover:bg-indigo-600 hover:text-white transition">
                            ${event.is_live ? 'Join Stream' : 'View Details'}
                        </a>
                    </div>
                </div>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-12 col-span-full">No upcoming events or live streams.</p>';
    } catch (err) { console.error(err); }
}

async function getAIExamAdvice() {
    try {
        const response = await fetch(`${API_BASE}/academic/exams/adaptive-difficulty`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const adviceEl = document.getElementById('aiExamAdvice');
        adviceEl.classList.remove('hidden');
        adviceEl.innerHTML = `
            <div class="flex items-center gap-3">
                <span class="px-3 py-1 bg-white text-indigo-600 rounded-full text-xs font-bold uppercase">${data.recommended_difficulty}</span>
                <p class="text-sm">${data.reason}</p>
            </div>
        `;
        showToast('AI analysis complete', 'success');
    } catch (err) { console.error(err); }
}

// AI Cheat Detection Mock
let tabSwitches = [];
window.addEventListener('blur', () => {
    tabSwitches.push(new Date().toISOString());
    if (tabSwitches.length > 3) {
        reportSuspiciousActivity();
    }
});

async function reportSuspiciousActivity() {
    try {
        const response = await fetch(`${API_BASE}/academic/exams/cheat-detection`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ patterns: tabSwitches })
        });
        const data = await response.json();
        if (data.is_suspicious) {
            console.warn('AI Cheat Detection:', data.alert);
            // In a real app, this would alert the proctor
        }
    } catch (err) { console.error(err); }
}

// CGPA PREDICTOR FIX
async function runCgpaPrediction() {
    try {
        const data = await authedGet('/predict');
        const cgpaVal = document.getElementById('predictedCgpaVal');
        if (cgpaVal) cgpaVal.textContent = data.predicted_cgpa;
        
        const feedbackEl = document.getElementById('cgpaFeedback');
        if (feedbackEl) {
            let feedback = "";
            if (data.predicted_cgpa >= 9.0) feedback = "Excellent! You're on track for a Gold Medal.";
            else if (data.predicted_cgpa >= 8.0) feedback = "Great performance! Keep it up.";
            else if (data.predicted_cgpa >= 7.0) feedback = "Good, but focus more on internals.";
            else feedback = "Needs significant improvement in attendance and marks.";
            feedbackEl.textContent = feedback;
        }

        const factorsGrid = document.getElementById('cgpaFactors');
        if (factorsGrid) {
            factorsGrid.innerHTML = `
                <div class="flex justify-between items-center text-sm">
                    <span class="text-gray-500 font-bold uppercase text-[10px]">Attendance Impact</span>
                    <span class="text-green-600 font-bold">+${data.factors.attendance_impact}</span>
                </div>
                <div class="flex justify-between items-center text-sm">
                    <span class="text-gray-500 font-bold uppercase text-[10px]">Internal Marks Impact</span>
                    <span class="text-blue-600 font-bold">+${data.factors.internal_impact}</span>
                </div>
            `;
        }
    } catch (err) { console.error(err); }
}

// RESUME BUILDER
async function loadResumeData() {
    try {
        const response = await fetch(`${API_BASE}/student/resume`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        if (data.resume_data) {
            const rd = data.resume_data;
            document.getElementById('resumeName').value = rd.name || '';
            document.getElementById('resumeEmail').value = rd.email || '';
            document.getElementById('resumeSummary').value = rd.summary || '';
            updateResumePreview();
        }
    } catch (err) { console.error(err); }
}

async function saveResumeData() {
    const name = document.getElementById('resumeName').value;
    const email = document.getElementById('resumeEmail').value;
    const summary = document.getElementById('resumeSummary').value;

    try {
        const response = await fetch(`${API_BASE}/student/resume`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ name, email, summary })
        });
        if (response.ok) {
            showToast('Resume saved!', 'success');
            updateResumePreview();
        }
    } catch (err) { console.error(err); }
}

function updateResumePreview() {
    const name = document.getElementById('resumeName').value || 'Your Name';
    const email = document.getElementById('resumeEmail').value || 'email@example.com';
    const summary = document.getElementById('resumeSummary').value || 'Your professional summary will appear here...';

    const preview = document.getElementById('resumePreview');
    if (!preview) return;
    preview.innerHTML = `
        <div class="text-center mb-8">
            <h1 class="text-3xl font-bold uppercase tracking-widest">${name}</h1>
            <p class="text-gray-500">${email}</p>
        </div>
        <div class="mb-6">
            <h2 class="text-lg font-bold border-b-2 border-gray-800 mb-2 uppercase">Professional Summary</h2>
            <p class="text-gray-700">${summary}</p>
        </div>
        <div class="mb-6">
            <h2 class="text-lg font-bold border-b-2 border-gray-800 mb-2 uppercase">Education</h2>
            <p class="text-gray-700 font-bold">Bachelor of Technology</p>
            <p class="text-gray-500 italic">Digital University | 2022 - 2026</p>
        </div>
    `;
}

async function analyzeResumeATS() {
    try {
        const response = await fetch(`${API_BASE}/placement/analyze-resume`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        if (response.ok) {
            document.getElementById('atsScoreCard').classList.remove('hidden');
            document.getElementById('atsScoreVal').textContent = `${data.score}%`;
            document.getElementById('atsFeedback').textContent = data.feedback;
            showToast('ATS Analysis Complete!', 'success');
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) { console.error(err); }
}

function exportResumePDF() {
    showToast('Generating PDF...', 'info');
    window.print();
}

function openModal(id) {
    document.getElementById(id).style.display = 'block';
}

function closeModal(id) {
    document.getElementById(id).style.display = 'none';
}

async function loadDashboard() {
    try {
        const data = await authedGet('/student/dashboard');
        
        // Update stats
        document.getElementById('attendanceRate').textContent = `${data.attendance_rate}%`;
        document.getElementById('avgMarks').textContent = data.average_marks;
        document.getElementById('completedAssignments').textContent = data.assignments_completed;
        document.getElementById('pendingTasks').textContent = data.pending_tasks;

        // Charts
        updateCharts(data);
        
        // Notifications & Recommendations
        loadNotifications();
        loadRecommendations();
    } catch (err) { console.error(err); }
}

async function loadNotifications() {
    try {
        const data = await authedGet('/notifications');
        const list = document.getElementById('notificationList');
        list.innerHTML = data.map(n => `
            <div class="p-3 border-b last:border-0">
                <p class="text-sm font-semibold">${n.title}</p>
                <p class="text-xs text-gray-500">${n.message}</p>
                <p class="text-[10px] text-gray-400 mt-1">${new Date(n.created_at).toLocaleString()}</p>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-4">No notifications.</p>';
    } catch (err) { console.error(err); }
}

async function loadRecommendations() {
    try {
        const data = await authedGet('/student/recommendations');
        const list = document.getElementById('recommendationList');
        list.innerHTML = data.items.map(item => `
            <div class="p-3 rounded bg-indigo-50 border border-indigo-100">
                <p class="text-sm font-bold text-indigo-900">${item.title}</p>
                <p class="text-xs text-indigo-700 mt-1">${item.description}</p>
                <span class="inline-block mt-2 text-[10px] bg-indigo-200 text-indigo-800 px-2 py-0.5 rounded font-bold uppercase">${item.type}</span>
            </div>
        `).join('') || '<p class="text-xs text-gray-500 italic">No recommendations yet.</p>';
    } catch (err) { console.error(err); }
}

function updateCharts(data) {
    const ctxAtt = document.getElementById('attendanceChart').getContext('2d');
    if (attendanceChart) attendanceChart.destroy();
    
    // Add forecast point
    const labels = data.attendance_history.map(h => h.date);
    const values = data.attendance_history.map(h => h.value);
    
    // Simple forecast: average of last 3 points
    const forecast = (values.slice(-3).reduce((a, b) => a + b, 0) / 3).toFixed(1);
    labels.push('Forecast');
    values.push(parseFloat(forecast));

    attendanceChart = new Chart(ctxAtt, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [{
                label: 'Attendance %',
                data: values,
                borderColor: '#4f46e5',
                tension: 0.4,
                fill: true,
                backgroundColor: 'rgba(79, 70, 229, 0.1)',
                pointBackgroundColor: (context) => context.dataIndex === values.length - 1 ? '#ef4444' : '#4f46e5',
                pointRadius: (context) => context.dataIndex === values.length - 1 ? 6 : 3
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });

    document.getElementById('attendanceForecast').textContent = `${forecast}%`;

    const ctxPerf = document.getElementById('performanceChart').getContext('2d');
    if (performanceChart) performanceChart.destroy();
    performanceChart = new Chart(ctxPerf, {
        type: 'bar',
        data: {
            labels: data.performance_data.map(p => p.subject),
            datasets: [{
                label: 'Marks',
                data: data.performance_data.map(p => p.marks),
                backgroundColor: '#818cf8',
                borderRadius: 5
            }]
        },
        options: { responsive: true, maintainAspectRatio: false }
    });
}

async function submitSelfAttendance() {
    try {
        const response = await fetch(`${API_BASE}/student/attendance/self`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        if (response.ok) {
            showToast('Attendance marked!', 'success');
            loadDashboard();
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) { console.error(err); }
}

function initSliderListeners() {
    const studySlider = document.getElementById('studyHoursInput');
    const sleepSlider = document.getElementById('sleepHoursInput');
    const attendanceSlider = document.getElementById('attendanceInput');

    studySlider.addEventListener('input', () => {
        document.getElementById('studyHoursDisplay').textContent = `${studySlider.value} hrs`;
    });

    sleepSlider.addEventListener('input', () => {
        document.getElementById('sleepHoursDisplay').textContent = `${sleepSlider.value} hrs`;
    });

    attendanceSlider.addEventListener('input', () => {
        document.getElementById('attendanceDisplay').textContent = `${attendanceSlider.value}%`;
    });
}

function getPredictionFeedback(marks) {
    if (marks >= 90) {
        return "🌟 Excellent! You're on track for top grades!";
    } else if (marks >= 75) {
        return "👍 Great job! Keep up the good work!";
    } else if (marks >= 60) {
        return "📚 Good, but you can improve by studying more!";
    } else {
        return "⚠️ Needs improvement! Increase study hours and attendance!";
    }
}

function getPredictionColor(marks) {
    if (marks >= 90) return '#4caf50';
    if (marks >= 75) return '#4fc3f7';
    if (marks >= 60) return '#ff9800';
    return '#f44336';
}

async function loadRecommendations() {
    try {
        const response = await fetch(`${API_BASE}/recommendations/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        const list = document.getElementById('myRecommendationsList');
        if (list) {
            list.innerHTML = data.recommendations.map(tip => `<li>${tip}</li>`).join('');
        }
        
        // Update dashboard with stream/dept info if available
        if (data.stream && data.dept_name) {
            const metaEl = document.getElementById('studentPersonalMeta');
            if (metaEl) {
                metaEl.textContent = `${data.stream.toUpperCase()} | ${data.dept_name}`;
            }
        }
    } catch (err) {
        console.error(err);
    }
}

let currentQuiz = null;

async function loadQuickQuiz() {
    try {
        const response = await fetch(`${API_BASE}/quizzes/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        currentQuiz = data;
        
        document.getElementById('quickQuizMeta').textContent = `Subject: ${data.subject_name} | ${data.time_limit_mins} mins`;
        const container = document.getElementById('quickQuizQuestions');
        container.innerHTML = data.questions.map((q, idx) => `
            <div class="p-3 bg-white rounded border border-gray-100">
                <p class="font-medium mb-2">${idx + 1}. ${q.text}</p>
                <div class="grid grid-cols-1 md:grid-cols-2 gap-2">
                    ${q.options.map((opt, oIdx) => `
                        <label class="flex items-center space-x-2 cursor-pointer p-2 hover:bg-gray-50 rounded">
                            <input type="radio" name="q${q.id}" value="${oIdx}" class="text-indigo-600">
                            <span class="text-sm">${opt}</span>
                        </label>
                    `).join('')}
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error('Failed to load quiz:', err);
    }
}

async function submitQuickQuiz() {
    if (!currentQuiz) return;
    let score = 0;
    currentQuiz.questions.forEach(q => {
        const selected = document.querySelector(`input[name="q${q.id}"]:checked`);
        if (selected && parseInt(selected.value) === q.answer) {
            score++;
        }
    });
    
    const resultEl = document.getElementById('quickQuizResult');
    resultEl.textContent = `Score: ${score}/${currentQuiz.questions.length}`;
    showToast('Quiz submitted!', 'success');
}

async function generateStudyPlanner() {
    const exam_date = document.getElementById('plannerExamDate').value;
    const weak_subjects = document.getElementById('plannerWeakSubjects').value;
    const hours_per_day = document.getElementById('plannerHours').value;
    
    try {
        const response = await fetch(`${API_BASE}/study-plans/me`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ exam_date, weak_subjects, hours_per_day })
        });
        const data = await response.json();
        
        const container = document.getElementById('studyPlannerSchedule');
        container.innerHTML = data.plan.map(p => `
            <div class="p-2 bg-white rounded border-l-4 border-teal-500 shadow-sm">
                <div class="flex justify-between items-start">
                    <span class="font-bold text-teal-800">${p.day}</span>
                    <span class="text-xs text-teal-600">${p.duration}</span>
                </div>
                <p class="text-sm font-medium mt-1">${p.topic}</p>
            </div>
        `).join('');
    } catch (err) {
        console.error('Failed to generate plan:', err);
    }
}

async function loadLearningHub() {
    try {
        const response = await fetch(`${API_BASE}/learning-hub/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        document.getElementById('learningHubOverall').textContent = `Overall progress: ${data.overall_progress}%`;
        const list = document.getElementById('learningHubList');
        list.innerHTML = data.resources.map(r => `
            <div class="flex items-center justify-between p-2 bg-white rounded shadow-sm">
                <div class="flex items-center space-x-2">
                    <i class="fas ${r.type === 'video' ? 'fa-video text-purple-500' : 'fa-file-pdf text-red-500'}"></i>
                    <span class="text-sm font-medium">${r.title}</span>
                </div>
                <div class="w-24 bg-gray-200 rounded-full h-1.5">
                    <div class="bg-teal-500 h-1.5 rounded-full" style="width: ${r.progress}%"></div>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error('Failed to load hub:', err);
    }
}



function initCharts(chartData) {
    const ctx1 = document.getElementById('attendanceChart');
    if (ctx1) {
        attendanceChart = new Chart(ctx1, {
            type: 'bar',
            data: {
                labels: chartData.labels,
                datasets: [{
                    label: 'Attendance %',
                    data: chartData.attendance,
                    backgroundColor: 'rgba(79, 195, 247, 0.6)'
                }]
            },
            options: { responsive: true, plugins: { legend: { labels: { color: '#e0e0e0' } } }, scales: { x: { ticks: { color: '#e0e0e0' } }, y: { ticks: { color: '#e0e0e0' } } } }
        });
    }

    const ctx2 = document.getElementById('performanceChart');
    if (ctx2) {
        performanceChart = new Chart(ctx2, {
            type: 'line',
            data: {
                labels: chartData.labels,
                datasets: [{
                    label: 'Study Hours',
                    data: chartData.study_hours,
                    borderColor: '#4fc3f7',
                    tension: 0.4
                }]
            },
            options: { responsive: true, plugins: { legend: { labels: { color: '#e0e0e0' } } }, scales: { x: { ticks: { color: '#e0e0e0' } }, y: { ticks: { color: '#e0e0e0' } } } }
        });
    }
}

async function loadNotes() {
    try {
        const response = await fetch(`${API_BASE}/notes`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const notes = await response.json();
        const container = document.getElementById('notesList');
        container.innerHTML = notes.map(note => `
            <div class="student-item">
                <div>
                    <h3>${note.course}</h3>
                    <p>Uploaded: ${new Date(note.uploaded_at).toLocaleDateString()}</p>
                </div>
                <a href="${API_BASE}/uploads/${note.file}" target="_blank" style="color: #4fc3f7;">Download</a>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function loadAnnouncements() {
    try {
        const response = await fetch(`${API_BASE}/announcements`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const announcements = await response.json();
        const container = document.getElementById('announcementsList');
        container.innerHTML = announcements.map(ann => `
            <div class="student-item">
                <p>${ann.message}</p>
                <small>${new Date(ann.created_at).toLocaleString()}</small>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

socket.on('new_announcement', (data) => {
    showToast('New announcement!', 'alert');
    loadAnnouncements();
});

function initChatbot() {
    const bubble = document.querySelector('.chatbot-bubble');
    const window = document.querySelector('.chatbot-window');
    const input = document.querySelector('.chatbot-input input');
    const button = document.querySelector('.chatbot-input button');
    const messages = document.querySelector('.chatbot-messages');

    if (!bubble) return;

    bubble.addEventListener('click', () => {
        window.style.display = window.style.display === 'flex' ? 'none' : 'flex';
    });

    const addMessage = (text, sender) => {
        const msg = document.createElement('div');
        msg.className = `message ${sender}`;
        msg.textContent = text;
        messages.appendChild(msg);
        messages.scrollTop = messages.scrollHeight;
    };

    const handleSend = async () => {
        const text = input.value.trim();
        if (!text) return;

        addMessage(text, 'user');
        input.value = '';

        try {
            const response = await fetch(`${API_BASE}/ai/doubt-solver`, {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${localStorage.getItem('token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ query: text })
            });
            const data = await response.json();
            addMessage(data.response, 'bot');
            if (data.related_topics) {
                addMessage(`Related: ${data.related_topics.join(', ')}`, 'bot');
            }
        } catch (err) {
            addMessage("Sorry, I'm having trouble connecting to the AI engine.", 'bot');
        }
    };

    button.addEventListener('click', handleSend);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSend();
    });
}

function initVoiceAssistant() {
    document.getElementById('voiceBtn').addEventListener('click', () => {
        const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
        recognition.lang = 'en-US';
        recognition.onresult = (event) => {
            const command = event.results[0][0].transcript;
            addMessage(command, 'user');
            const response = getBotResponse(command);
            addMessage(response, 'bot');
            speechSynthesis.speak(new SpeechSynthesisUtterance(response));
        };
        recognition.start();
    });
}

async function loadPrediction() {
    try {
        const response = await fetch(`${API_BASE}/predict`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ study_hours: 3.5, sleep_hours: 7.5, attendance: 85 })
        });
        const data = await response.json();
        updatePredictionDisplay(data.predicted_marks);
    } catch (err) {
        console.error(err);
    }
}

function updatePredictionDisplay(marks) {
    const marksEl = document.getElementById('predictedMarks');
    const feedbackEl = document.getElementById('predictionFeedback');
    
    marksEl.textContent = `${marks}%`;
    marksEl.style.color = getPredictionColor(marks);
    feedbackEl.textContent = getPredictionFeedback(marks);
}

async function predictMarks() {
    try {
        const response = await fetch(`${API_BASE}/predict`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                study_hours: parseFloat(document.getElementById('studyHoursInput').value) || 0,
                sleep_hours: parseFloat(document.getElementById('sleepHoursInput').value) || 0,
                attendance: parseFloat(document.getElementById('attendanceInput').value) || 0
            })
        });
        const data = await response.json();
        updatePredictionDisplay(data.predicted_marks);
        showToast('Prediction updated!', 'success');
    } catch (err) {
        showToast('Prediction failed!', 'error');
    }
}

function showToast(message, type) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = message;
    toast.className = type;
    toast.style.display = 'block';
    setTimeout(() => toast.style.display = 'none', 3000);
}

// Learning Center Functions
async function filterDepartments(stream) {
    const streamGrid = document.getElementById('streamGrid');
    const deptContainer = document.getElementById('deptContainer');
    const deptGrid = document.getElementById('deptGrid');
    const backBtn = document.getElementById('learningBackBtn');
    const streamTitle = document.getElementById('currentStreamTitle');

    try {
        const response = await fetch(`${API_BASE}/master/departments?stream=${stream}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        streamGrid.classList.add('hidden');
        deptContainer.classList.remove('hidden');
        if (backBtn) backBtn.classList.remove('hidden');
        
        const streamColor = getStreamColor(stream);
        streamTitle.textContent = `${stream.charAt(0).toUpperCase() + stream.slice(1)} Departments`;
        streamTitle.className = `text-xl font-bold mb-4 ${streamColor}`;

        deptGrid.innerHTML = data.items.map(dept => `
            <div onclick="loadSubjects(${dept.id}, '${dept.name}', '${stream}')" class="department-card card-shadow p-4 bg-white rounded-lg border-l-4 ${getStreamBorder(stream)} hover:bg-gray-50 transition cursor-pointer">
                <div class="flex items-center space-x-3">
                    <i class="${getStreamIcon(stream)} ${streamColor} text-2xl"></i>
                    <h4 class="font-bold text-gray-800">${dept.name}</h4>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
        showToast('Failed to load departments', 'error');
    }
}

function getStreamColor(stream) {
    switch(stream) {
        case 'engineering': return 'text-blue-600';
        case 'medical': return 'text-red-600';
        case 'commerce': return 'text-green-600';
        default: return 'text-gray-600';
    }
}

function getStreamBorder(stream) {
    switch(stream) {
        case 'engineering': return 'border-blue-500';
        case 'medical': return 'border-red-500';
        case 'commerce': return 'border-green-500';
        default: return 'border-gray-500';
    }
}

function getStreamIcon(stream) {
    switch(stream) {
        case 'engineering': return 'fas fa-cog';
        case 'medical': return 'fas fa-stethoscope';
        case 'commerce': return 'fas fa-chart-line';
        default: return 'fas fa-graduation-cap';
    }
}

async function loadSubjects(deptId, deptName, stream) {
    const deptContainer = document.getElementById('deptContainer');
    const subjectContainer = document.getElementById('subjectContainer');
    const subjectList = document.getElementById('subjectList');
    const deptTitle = document.getElementById('currentDeptTitle');

    try {
        const response = await fetch(`${API_BASE}/master/subjects?department_id=${deptId}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        deptContainer.classList.add('hidden');
        subjectContainer.classList.remove('hidden');
        
        const streamColor = getStreamColor(stream);
        deptTitle.textContent = `Subjects in ${deptName}`;
        deptTitle.className = `text-xl font-bold mb-4 ${streamColor}`;

        subjectList.innerHTML = data.items.map(sub => `
            <div onclick="loadMaterials(${sub.id}, '${sub.name}', '${stream}')" class="p-4 bg-white rounded-lg shadow-sm border hover:${getStreamBorder(stream).replace('border-', 'border-')} transition cursor-pointer flex justify-between items-center">
                <div>
                    <p class="text-xs text-gray-500 font-mono">${sub.code || 'N/A'}</p>
                    <h4 class="font-bold text-gray-800">${sub.name}</h4>
                </div>
                <i class="fas fa-chevron-right ${streamColor} opacity-50"></i>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
        showToast('Failed to load subjects', 'error');
    }
}

async function loadMaterials(subjId, subjName, stream) {
    const subjectContainer = document.getElementById('subjectContainer');
    const materialContainer = document.getElementById('materialContainer');
    const materialGrid = document.getElementById('materialGrid');
    const subjectTitle = document.getElementById('currentSubjectTitle');

    try {
        const response = await fetch(`${API_BASE}/master/materials?subject_id=${subjId}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        subjectContainer.classList.add('hidden');
        materialContainer.classList.remove('hidden');
        
        const streamColor = getStreamColor(stream);
        subjectTitle.textContent = `Materials for ${subjName}`;
        subjectTitle.className = `text-xl font-bold mb-4 ${streamColor}`;

        if (data.items.length === 0) {
            materialGrid.innerHTML = '<p class="col-span-full text-center text-gray-500 py-8">No materials found for this subject.</p>';
        } else {
            materialGrid.innerHTML = data.items.map(m => `
                <div class="stats-card card-shadow p-6">
                    <div class="flex items-start justify-between mb-4">
                        <div class="w-12 h-12 ${getMaterialBg(m.material_type)} rounded-lg flex items-center justify-center">
                            <i class="${getMaterialIcon(m.material_type)} ${getMaterialText(m.material_type)} text-xl"></i>
                        </div>
                        <span class="text-xs font-bold uppercase px-2 py-1 rounded bg-gray-100 text-gray-600">${m.material_type}</span>
                    </div>
                    <h4 class="font-bold text-lg mb-2">${m.title}</h4>
                    <p class="text-sm text-gray-600 mb-4 line-clamp-2">${m.description || 'No description available.'}</p>
                    <a href="${m.url}" target="_blank" class="inline-flex items-center text-blue-600 font-semibold hover:text-blue-800">
                        View Resource <i class="fas fa-external-link-alt ml-2 text-xs"></i>
                    </a>
                </div>
            `).join('');
        }
    } catch (err) {
        console.error(err);
        showToast('Failed to load materials', 'error');
    }
}

function getMaterialIcon(type) {
    switch(type) {
        case 'note': return 'fas fa-file-alt';
        case 'pdf': return 'fas fa-file-pdf';
        case 'ppt': return 'fas fa-file-powerpoint';
        case 'video': return 'fas fa-video';
        default: return 'fas fa-link';
    }
}

function getMaterialBg(type) {
    switch(type) {
        case 'note': return 'bg-blue-100';
        case 'pdf': return 'bg-red-100';
        case 'ppt': return 'bg-orange-100';
        case 'video': return 'bg-purple-100';
        default: return 'bg-gray-100';
    }
}

function getMaterialText(type) {
    switch(type) {
        case 'note': return 'text-blue-600';
        case 'pdf': return 'text-red-600';
        case 'ppt': return 'text-orange-600';
        case 'video': return 'text-purple-600';
        default: return 'text-gray-600';
    }
}

function learningGoBack() {
    backToStreams();
}

function backToStreams() {
    const streamGrid = document.getElementById('streamGrid');
    const deptContainer = document.getElementById('deptContainer');
    const subjectContainer = document.getElementById('subjectContainer');
    const materialContainer = document.getElementById('materialContainer');
    const backBtn = document.getElementById('learningBackBtn');

    if (!materialContainer.classList.contains('hidden')) {
        materialContainer.classList.add('hidden');
        subjectContainer.classList.remove('hidden');
    } else if (!subjectContainer.classList.contains('hidden')) {
        subjectContainer.classList.add('hidden');
        deptContainer.classList.remove('hidden');
    } else {
        deptContainer.classList.add('hidden');
        streamGrid.classList.remove('hidden');
        backBtn.classList.add('hidden');
    }
}



// COMPETITIVE EXAMS
async function loadMockTests() {
    const type = document.getElementById('examTypeFilter').value;
    try {
        const response = await fetch(`${API_BASE}/exams/mock-tests?type=${type}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const grid = document.getElementById('mockTestsGrid');
        
        grid.innerHTML = data.items.map(test => `
            <div class="bg-white p-6 rounded-lg shadow-md border-t-4 border-red-500 hover:shadow-lg transition">
                <div class="flex justify-between items-start mb-4">
                    <span class="bg-red-100 text-red-700 text-xs font-bold px-2 py-1 rounded">${test.exam_type}</span>
                    <span class="text-xs text-gray-500"><i class="fas fa-clock mr-1"></i>${test.duration_mins} mins</span>
                </div>
                <h4 class="font-bold text-lg mb-2">${test.title}</h4>
                <p class="text-sm text-gray-600 mb-4">Total Marks: ${test.total_marks}</p>
                <button onclick="startMockTest(${test.id}, '${test.title}')" class="w-full py-2 bg-gray-800 text-white rounded font-bold hover:bg-black transition">
                    Start Mock Test
                </button>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function startMockTest(testId, title) {
    const score = prompt(`Simulating ${title}. Enter your score (0-100):`);
    if (score === null || score === "") return;
    
    try {
        const response = await fetch(`${API_BASE}/exams/submit`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ test_id: testId, score: parseInt(score) })
        });
        const data = await response.json();
        if (response.ok) {
            alert(`Test Submitted!\nPredicted Rank: ${data.rank}\nPercentile: ${data.percentile}%`);
            loadMockTests();
        }
    } catch (err) {
        console.error(err);
    }
}

// ACADEMIC PLANNER
async function loadAcademicGoals() {
    try {
        const response = await fetch(`${API_BASE}/planner/goals`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('goalsList');
        
        list.innerHTML = data.items.map(goal => `
            <div class="bg-white p-4 rounded-lg shadow border-l-4 ${goal.status === 'completed' ? 'border-green-500' : 'border-yellow-500'} flex justify-between items-center">
                <div>
                    <h4 class="font-bold text-gray-800">${goal.goal_text}</h4>
                    <p class="text-xs text-gray-500">Target: ${goal.target_date || 'No date'}</p>
                </div>
                <span class="text-xs font-bold uppercase ${goal.status === 'completed' ? 'text-green-600' : 'text-yellow-600'}">
                    ${goal.status}
                </span>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function addGoal() {
    const goal_text = document.getElementById('goalText').value;
    const target_date = document.getElementById('goalDate').value;
    
    if (!goal_text) return showToast('Please enter a goal', 'error');
    
    try {
        const response = await fetch(`${API_BASE}/planner/goals`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ goal_text, target_date })
        });
        if (response.ok) {
            showToast('Goal added!', 'success');
            closeModal('newGoalModal');
            loadAcademicGoals();
        }
    } catch (err) {
        console.error(err);
    }
}

// CGPA PREDICTOR
async function runCgpaPrediction() {
    try {
        const response = await fetch(`${API_BASE}/cgpa/predict`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        document.getElementById('predictedCgpaVal').textContent = data.predicted_cgpa;
        
        const factorsEl = document.getElementById('cgpaFactors');
        factorsEl.innerHTML = `
            <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                <span class="text-sm font-medium">Attendance Impact</span>
                <span class="text-sm font-bold text-blue-600">${data.factors.attendance}%</span>
            </div>
            <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                <span class="text-sm font-medium">Study Consistency</span>
                <span class="text-sm font-bold text-green-600">${data.factors.study_hours} hrs/day</span>
            </div>
            <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                <span class="text-sm font-medium">Sleep Health</span>
                <span class="text-sm font-bold text-orange-600">${data.factors.sleep_hours} hrs/day</span>
            </div>
        `;
        
        let feedback = "";
        if (data.predicted_cgpa >= 9.0) feedback = "Excellent! You're among the top 5%.";
        else if (data.predicted_cgpa >= 8.0) feedback = "Great performance! Keep it up.";
        else if (data.predicted_cgpa >= 7.0) feedback = "Good, but there's room for growth.";
        else feedback = "Focus on increasing study hours to boost your score.";
        
        document.getElementById('cgpaFeedback').textContent = feedback;
        
    } catch (err) {
        console.error(err);
    }
}



// AI DOUBT SOLVER
async function solveDoubt() {
    const subject = document.getElementById('doubtSubject').value;
    const doubt = document.getElementById('doubtText').value;
    const btn = document.getElementById('solveDoubtBtn');
    const responseEl = document.getElementById('doubtResponse');

    if (!doubt) return showToast('Please enter your doubt', 'error');

    btn.disabled = true;
    btn.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> Analyzing Doubt...';

    try {
        const response = await fetch(`${API_BASE}/ai/solve-doubt`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ subject, doubt })
        });
        const data = await response.json();
        
        if (response.ok) {
            document.getElementById('doubtExplanation').textContent = data.explanation;
            document.getElementById('doubtNotes').innerHTML = data.notes.map(n => `<li>${n}</li>`).join('');
            document.getElementById('doubtTopics').innerHTML = data.related_topics.map(t => `
                <span class="bg-amber-100 text-amber-700 text-xs font-bold px-3 py-1 rounded-full border border-amber-200">
                    ${t}
                </span>
            `).join('');
            
            responseEl.classList.remove('hidden');
            responseEl.scrollIntoView({ behavior: 'smooth' });
        }
    } catch (err) {
        console.error(err);
        showToast('Failed to solve doubt', 'error');
    } finally {
        btn.disabled = false;
        btn.innerHTML = '<i class="fas fa-magic mr-2"></i> Get AI Explanation';
    }
}

// DIGITAL LIBRARY
let isLibraryHistoryView = false;

function toggleLibraryView() {
    const booksView = document.getElementById('libraryBooksView');
    const historyView = document.getElementById('libraryHistoryView');
    const viewBtn = document.getElementById('libraryViewBtn');
    
    isLibraryHistoryView = !isLibraryHistoryView;
    
    if (isLibraryHistoryView) {
        booksView.classList.add('hidden');
        historyView.classList.remove('hidden');
        viewBtn.innerHTML = '<i class="fas fa-book mr-2"></i> Browse Books';
        loadLibraryHistory();
    } else {
        booksView.classList.remove('hidden');
        historyView.classList.add('hidden');
        viewBtn.innerHTML = '<i class="fas fa-history mr-2"></i> Borrow History';
        loadLibraryBooks();
    }
}

async function loadLibraryBooks() {
    const search = document.getElementById('librarySearch').value;
    try {
        const response = await fetch(`${API_BASE}/library/books?search=${search}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const grid = document.getElementById('libraryBooksGrid');
        
        grid.innerHTML = data.items.map(book => `
            <div class="bg-white p-4 rounded-lg shadow-md border hover:border-blue-500 transition">
                <div class="h-40 bg-gray-100 rounded mb-4 flex items-center justify-center relative group">
                    <i class="fas fa-book text-4xl text-blue-300"></i>
                    ${book.pdf_url ? `
                        <div class="absolute inset-0 bg-black bg-opacity-40 opacity-0 group-hover:opacity-100 transition flex items-center justify-center">
                            <a href="${book.pdf_url}" target="_blank" class="bg-white text-gray-800 px-3 py-1 rounded-full text-xs font-bold">
                                <i class="fas fa-file-pdf mr-1 text-red-500"></i> Read PDF
                            </a>
                        </div>
                    ` : ''}
                </div>
                <h4 class="font-bold text-lg line-clamp-1">${book.title}</h4>
                <p class="text-sm text-gray-600">${book.author}</p>
                <div class="flex justify-between items-center mt-4">
                    <span class="text-xs font-bold text-blue-600 bg-blue-50 px-2 py-1 rounded">${book.category}</span>
                    <span class="text-xs ${book.available_copies > 0 ? 'text-green-600' : 'text-red-600'}">
                        ${book.available_copies} copies left
                    </span>
                </div>
                <button onclick="borrowBook(${book.id})" 
                        class="w-full mt-4 py-2 rounded bg-blue-600 text-white text-sm font-bold hover:bg-blue-700 transition"
                        ${book.available_copies === 0 ? 'disabled' : ''}>
                    Borrow Book
                </button>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function loadLibraryHistory() {
    try {
        const response = await fetch(`${API_BASE}/library/borrows/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const tbody = document.getElementById('libraryHistoryTableBody');
        
        tbody.innerHTML = data.items.map(b => `
            <tr class="hover:bg-gray-50">
                <td class="p-4 border-b font-medium">${b.title}</td>
                <td class="p-4 border-b text-sm text-gray-600">${new Date(b.borrowed_at).toLocaleDateString()}</td>
                <td class="p-4 border-b text-sm text-gray-600">${new Date(b.due_date).toLocaleDateString()}</td>
                <td class="p-4 border-b">
                    <span class="px-2 py-1 rounded-full text-[10px] font-bold uppercase ${
                        b.status === 'returned' ? 'bg-green-100 text-green-700' : 
                        (new Date(b.due_date) < new Date() ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700')
                    }">
                        ${b.status === 'borrowed' && new Date(b.due_date) < new Date() ? 'overdue' : b.status}
                    </span>
                </td>
                <td class="p-4 border-b">
                    ${b.status === 'borrowed' ? `
                        <button onclick="returnBook(${b.id})" class="text-xs text-indigo-600 font-bold hover:underline">
                            Return Book
                        </button>
                    ` : '-'}
                </td>
            </tr>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function returnBook(borrowId) {
    try {
        const response = await fetch(`${API_BASE}/library/return`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ borrow_id: borrowId })
        });
        if (response.ok) {
            showToast('Book returned successfully!', 'success');
            loadLibraryHistory();
        }
    } catch (err) {
        console.error(err);
    }
}

async function borrowBook(bookId) {
    try {
        const response = await fetch(`${API_BASE}/library/borrow`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ book_id: bookId })
        });
        const data = await response.json();
        if (response.ok) {
            showToast('Book borrowed successfully!', 'success');
            loadLibraryBooks();
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) {
        console.error(err);
    }
}

// PLACEMENT PORTAL
let currentPlacementFilter = 'full-time';

async function filterPlacements(type) {
    currentPlacementFilter = type;
    
    // Update UI buttons
    const ftBtn = document.getElementById('btnJobFT');
    const inBtn = document.getElementById('btnJobIntern');
    
    if (type === 'full-time') {
        ftBtn.classList.add('bg-white', 'shadow-sm');
        ftBtn.classList.remove('text-gray-500');
        inBtn.classList.remove('bg-white', 'shadow-sm');
        inBtn.classList.add('text-gray-500');
    } else {
        inBtn.classList.add('bg-white', 'shadow-sm');
        inBtn.classList.remove('text-gray-500');
        ftBtn.classList.remove('bg-white', 'shadow-sm');
        ftBtn.classList.add('text-gray-500');
    }
    
    loadPlacementJobs();
}

async function loadPlacementJobs() {
    try {
        const response = await fetch(`${API_BASE}/placement/jobs?type=${currentPlacementFilter}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('placementJobsList');
        
        // Use Promise.all to check eligibility for all jobs in parallel
        const jobsWithEligibility = await Promise.all(data.items.map(async job => {
            const elRes = await fetch(`${API_BASE}/placement/check-eligibility/${job.id}`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
            });
            const elData = await elRes.json();
            return { ...job, eligibility: elData };
        }));

        list.innerHTML = jobsWithEligibility.map(job => `
            <div class="bg-white p-6 rounded-lg shadow-md border-l-4 ${currentPlacementFilter === 'internship' ? 'border-orange-500' : 'border-blue-600'}">
                <div class="flex justify-between items-start">
                    <div>
                        <div class="flex items-center gap-3 mb-1">
                            <h4 class="text-xl font-bold text-gray-800">${job.role}</h4>
                            <span class="text-[10px] font-black uppercase px-2 py-0.5 rounded ${job.eligibility.eligible ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}">
                                ${job.eligibility.eligible ? 'Eligible' : 'Ineligible'}
                            </span>
                        </div>
                        <p class="text-blue-600 font-semibold">${job.company_name}</p>
                    </div>
                    <span class="${currentPlacementFilter === 'internship' ? 'bg-orange-100 text-orange-800' : 'bg-green-100 text-green-800'} text-xs font-bold px-3 py-1 rounded-full">
                        ${job.salary_package}
                    </span>
                </div>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4 mt-4 text-sm text-gray-600">
                    <div><i class="fas fa-map-marker-alt mr-2"></i>${job.location}</div>
                    <div><i class="fas fa-calendar-alt mr-2"></i>Deadline: ${job.deadline}</div>
                    <div class="col-span-2"><i class="fas fa-graduation-cap mr-2"></i>Req: ${job.min_cgpa} CGPA | ${job.min_attendance}% Att.</div>
                </div>
                ${!job.eligibility.eligible ? `
                    <div class="mt-3 p-2 bg-red-50 text-red-600 text-[10px] font-bold rounded border border-red-100">
                        <i class="fas fa-exclamation-circle mr-1"></i> ${job.eligibility.reasons.join(', ')}
                    </div>
                ` : ''}
                <button onclick="applyForJob(${job.id})" 
                        class="mt-4 px-6 py-2 ${!job.eligibility.eligible ? 'bg-gray-300 cursor-not-allowed' : (currentPlacementFilter === 'internship' ? 'bg-orange-600 hover:bg-orange-700' : 'bg-blue-600 hover:bg-blue-700')} text-white rounded transition font-bold"
                        ${!job.eligibility.eligible ? 'disabled' : ''}>
                    ${job.eligibility.eligible ? 'Apply Now' : 'Criteria Not Met'}
                </button>
            </div>
        `).join('') || `<p class="text-center text-gray-500 py-12">No ${currentPlacementFilter} opportunities available at the moment.</p>`;

        loadPlacementApplications();
        loadPlacementInterviews();
        loadPlacementCertificates();
        loadPlacementSummary();

    } catch (err) {
        console.error(err);
    }
}

async function loadPlacementApplications() {
    try {
        const response = await fetch(`${API_BASE}/placement/applications/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('placementApplicationsList');
        
        list.innerHTML = data.items.map(app => `
            <div class="p-3 bg-gray-50 rounded border">
                <div class="flex justify-between items-start">
                    <p class="font-bold text-sm">${app.role}</p>
                    <span class="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded ${
                        app.status === 'offered' ? 'bg-green-100 text-green-700' : 
                        (app.status === 'rejected' ? 'bg-red-100 text-red-700' : 'bg-blue-100 text-blue-700')
                    }">${app.status}</span>
                </div>
                <p class="text-xs text-blue-600">${app.company_name}</p>
                <p class="text-[10px] text-gray-400 mt-2">Applied: ${new Date(app.applied_at).toLocaleDateString()}</p>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function loadPlacementInterviews() {
    try {
        const response = await fetch(`${API_BASE}/placement/interviews/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('placementInterviewsList');
        
        if (data.items.length === 0) {
            list.innerHTML = '<p class="text-xs text-gray-500 italic">No upcoming interviews.</p>';
            return;
        }

        list.innerHTML = data.items.map(i => `
            <div class="p-3 bg-violet-50 rounded border border-violet-100">
                <p class="font-bold text-sm text-violet-800">${i.company_name}</p>
                <p class="text-xs text-violet-600">${i.role}</p>
                <div class="flex items-center mt-2 text-xs text-violet-500">
                    <i class="fas fa-calendar-alt mr-2"></i> ${new Date(i.scheduled_at).toLocaleString()}
                </div>
                ${i.meeting_link ? `
                    <a href="${i.meeting_link}" target="_blank" class="mt-2 inline-block text-[10px] bg-violet-600 text-white px-2 py-1 rounded">
                        Join Interview
                    </a>
                ` : ''}
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function loadPlacementCertificates() {
    try {
        const response = await fetch(`${API_BASE}/placement/certificates/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('placementCertificatesList');
        
        list.innerHTML = data.items.map(c => `
            <div class="p-3 bg-emerald-50 rounded border border-emerald-100 flex justify-between items-center">
                <div>
                    <p class="font-bold text-sm text-emerald-800">${c.title}</p>
                    <p class="text-xs text-emerald-600">${c.issuer}</p>
                </div>
                ${c.certificate_url ? `
                    <a href="${c.certificate_url}" target="_blank" class="text-emerald-500 hover:text-emerald-700">
                        <i class="fas fa-external-link-alt"></i>
                    </a>
                ` : ''}
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function addPlacementCertificate() {
    const title = document.getElementById('certificateTitle').value;
    const issuer = document.getElementById('certificateIssuer').value;
    const category = document.getElementById('certificateCategory').value;
    const issue_date = document.getElementById('certificateDate').value;
    const certificate_url = document.getElementById('certificateUrl').value;

    if (!title || !issuer) return showToast('Title and Issuer are required', 'error');

    try {
        const response = await fetch(`${API_BASE}/placement/certificates/me`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ title, issuer, category, issue_date, certificate_url })
        });
        if (response.ok) {
            showToast('Certificate added!', 'success');
            document.getElementById('certificateTitle').value = '';
            document.getElementById('certificateIssuer').value = '';
            document.getElementById('certificateUrl').value = '';
            loadPlacementCertificates();
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadPlacementSummary() {
    try {
        const appsRes = await fetch(`${API_BASE}/placement/applications/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const appsData = await appsRes.json();
        
        const certsRes = await fetch(`${API_BASE}/placement/certificates/me`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const certsData = await certsRes.json();

        const summaryEl = document.getElementById('placementSummary');
        summaryEl.innerHTML = `
            <div class="bg-white p-4 rounded-lg shadow-sm border text-center">
                <p class="text-2xl font-bold text-blue-600">${appsData.items.length}</p>
                <p class="text-xs text-gray-500 uppercase font-bold">Applications</p>
            </div>
            <div class="bg-white p-4 rounded-lg shadow-sm border text-center">
                <p class="text-2xl font-bold text-emerald-600">${certsData.items.length}</p>
                <p class="text-xs text-gray-500 uppercase font-bold">Certifications</p>
            </div>
            <div class="bg-white p-4 rounded-lg shadow-sm border text-center">
                <p class="text-2xl font-bold text-violet-600">${appsData.items.filter(a => a.status === 'interview').length}</p>
                <p class="text-xs text-gray-500 uppercase font-bold">Interviews</p>
            </div>
            <div class="bg-white p-4 rounded-lg shadow-sm border text-center">
                <p class="text-2xl font-bold text-green-600">${appsData.items.filter(a => a.status === 'offered').length}</p>
                <p class="text-xs text-gray-500 uppercase font-bold">Offers</p>
            </div>
        `;
    } catch (err) {
        console.error(err);
    }
}

async function applyForJob(jobId) {
    try {
        const response = await fetch(`${API_BASE}/placement/apply`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ job_id: jobId })
        });
        if (response.ok) {
            showToast('Application submitted!', 'success');
        } else {
            showToast('Failed to apply', 'error');
        }
    } catch (err) {
        console.error(err);
    }
}

// CAMPUS SERVICES
async function loadCampusServices() {
    try {
        // Load Hostels
        const hostelRes = await fetch(`${API_BASE}/campus/hostels`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const hostelData = await hostelRes.json();
        
        const hostelStatus = document.getElementById('hostelStatus');
        if (hostelData.my_allocation) {
            hostelStatus.innerHTML = `<span class="bg-green-100 text-green-800 px-2 py-1 rounded">Currently Allocated: ${hostelData.my_allocation.block} - Room ${hostelData.my_allocation.room_number}</span>`;
        } else {
            hostelStatus.innerHTML = `<span class="bg-yellow-100 text-yellow-800 px-2 py-1 rounded">No room allocated yet.</span>`;
        }

        document.getElementById('hostelInfo').innerHTML = hostelData.items.map(h => `
            <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                <div>
                    <p class="font-bold">${h.block} - Room ${h.room_number}</p>
                    <p class="text-xs text-gray-500">Available: ${h.available_slots} / ${h.capacity} | Fee: ₹${h.fee_per_sem}</p>
                </div>
                <button onclick="bookHostelRoom(${h.id})" 
                        class="text-xs bg-indigo-600 text-white px-3 py-1 rounded hover:bg-indigo-700 transition"
                        ${hostelData.my_allocation || h.available_slots === 0 ? 'disabled' : ''}>
                    ${hostelData.my_allocation ? 'Allocated' : 'Book Room'}
                </button>
            </div>
        `).join('');

        // Load Transport
        const transportRes = await fetch(`${API_BASE}/campus/transport-routes`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const transportData = await transportRes.json();
        
        const transportStatus = document.getElementById('transportStatus');
        if (transportData.my_allocation) {
            transportStatus.innerHTML = `<span class="bg-green-100 text-green-800 px-2 py-1 rounded">Registered: ${transportData.my_allocation.route_name} (${transportData.my_allocation.pickup_point})</span>`;
        } else {
            transportStatus.innerHTML = `<span class="bg-yellow-100 text-yellow-800 px-2 py-1 rounded">No transport registered.</span>`;
        }

        document.getElementById('transportInfo').innerHTML = transportData.items.map(r => `
            <div class="flex justify-between items-center p-3 bg-gray-50 rounded">
                <div>
                    <p class="font-bold">${r.route_name} (${r.bus_number})</p>
                    <p class="text-xs text-gray-500">Driver: ${r.driver_name} | Contact: ${r.driver_contact}</p>
                    <p class="text-xs text-gray-500">Fee: ₹${r.fee_per_sem}</p>
                </div>
                <button onclick="registerTransport(${r.id})" 
                        class="text-xs bg-blue-600 text-white px-3 py-1 rounded hover:bg-blue-700 transition"
                        ${transportData.my_allocation ? 'disabled' : ''}>
                    ${transportData.my_allocation ? 'Registered' : 'Register'}
                </button>
            </div>
        `).join('');

        // Load Complaints
        loadCampusComplaints();

    } catch (err) {
        console.error(err);
        showToast('Failed to load campus services', 'error');
    }
}

async function bookHostelRoom(roomId) {
    try {
        const response = await fetch(`${API_BASE}/campus/hostel/book`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ room_id: roomId })
        });
        const data = await response.json();
        if (response.ok) {
            showToast('Room booked successfully!', 'success');
            loadCampusServices();
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) {
        console.error(err);
    }
}

async function registerTransport(routeId) {
    const pickup_point = prompt("Enter your pickup point:");
    if (!pickup_point) return;

    try {
        const response = await fetch(`${API_BASE}/campus/transport/register`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ route_id: routeId, pickup_point })
        });
        const data = await response.json();
        if (response.ok) {
            showToast('Transport registered successfully!', 'success');
            loadCampusServices();
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) {
        console.error(err);
    }
}

async function submitCampusComplaint() {
    const category = document.getElementById('complaintCategory').value;
    const subject = document.getElementById('complaintSubject').value;
    const description = document.getElementById('complaintDescription').value;

    if (!subject || !description) return showToast('Please fill all fields', 'error');

    try {
        const response = await fetch(`${API_BASE}/campus/complaints`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ category, subject, description })
        });
        if (response.ok) {
            showToast('Complaint submitted!', 'success');
            document.getElementById('complaintSubject').value = '';
            document.getElementById('complaintDescription').value = '';
            loadCampusComplaints();
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadCampusComplaints() {
    try {
        const response = await fetch(`${API_BASE}/campus/complaints`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('complaintsList');
        
        list.innerHTML = data.items.map(c => `
            <div class="p-3 bg-gray-50 rounded border-l-4 ${c.status === 'open' ? 'border-red-400' : 'border-green-400'}">
                <div class="flex justify-between items-start">
                    <p class="font-bold text-sm">${c.subject}</p>
                    <span class="text-[10px] uppercase font-bold px-1.5 py-0.5 rounded ${c.status === 'open' ? 'bg-red-100 text-red-700' : 'bg-green-100 text-green-700'}">
                        ${c.status}
                    </span>
                </div>
                <p class="text-xs text-gray-600 mt-1">${c.description}</p>
                <p class="text-[10px] text-gray-400 mt-2">${c.category.toUpperCase()} | ${new Date(c.created_at).toLocaleDateString()}</p>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

// DISCUSSION FORUM
let currentTopicId = null;

async function loadForumTopics() {
    try {
        const response = await fetch(`${API_BASE}/forum/topics`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('forumTopicsList');
        
        list.innerHTML = data.items.map(topic => `
            <div onclick="openTopicDetails(${topic.id}, '${topic.title.replace(/'/g, "\\'")}', '${topic.description.replace(/'/g, "\\'")}')" 
                 class="bg-white p-4 rounded-lg shadow border hover:shadow-md transition cursor-pointer">
                <div class="flex items-start justify-between">
                    <div>
                        <h4 class="font-bold text-lg text-gray-800">${topic.title}</h4>
                        <p class="text-sm text-gray-600 mt-1">${topic.description}</p>
                        <div class="flex items-center mt-3 text-xs text-gray-400 space-x-4">
                            <span><i class="fas fa-user mr-1"></i>${topic.author_name}</span>
                            <span><i class="fas fa-clock mr-1"></i>${new Date(topic.created_at).toLocaleDateString()}</span>
                        </div>
                    </div>
                    <div class="text-center bg-gray-50 p-2 rounded w-16">
                        <p class="font-bold text-blue-600">${topic.reply_count || 0}</p>
                        <p class="text-[10px] uppercase text-gray-500">Replies</p>
                    </div>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function createForumTopic() {
    const title = document.getElementById('newTopicTitle').value;
    const description = document.getElementById('newTopicDesc').value;

    if (!title) return showToast('Title is required', 'error');

    try {
        const response = await fetch(`${API_BASE}/forum/topics`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ title, description })
        });
        if (response.ok) {
            showToast('Topic created!', 'success');
            closeModal('newTopicModal');
            document.getElementById('newTopicTitle').value = '';
            document.getElementById('newTopicDesc').value = '';
            loadForumTopics();
        }
    } catch (err) {
        console.error(err);
    }
}

async function openTopicDetails(topicId, title, description) {
    currentTopicId = topicId;
    document.getElementById('modalTopicTitle').textContent = title;
    document.getElementById('modalTopicDesc').textContent = description;
    document.getElementById('modalRepliesList').innerHTML = '<p class="text-center text-gray-500">Loading replies...</p>';
    
    openModal('topicDetailsModal');
    loadTopicReplies(topicId);
}

async function loadTopicReplies(topicId) {
    try {
        const response = await fetch(`${API_BASE}/forum/topics/${topicId}/replies`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('modalRepliesList');
        
        if (data.items.length === 0) {
            list.innerHTML = '<p class="text-center text-gray-500 py-4">No replies yet. Be the first to reply!</p>';
            return;
        }

        list.innerHTML = data.items.map(r => `
            <div class="p-3 bg-gray-50 rounded border">
                <div class="flex justify-between items-center mb-1">
                    <span class="font-bold text-xs text-indigo-600">${r.author_name}</span>
                    <span class="text-[10px] text-gray-400">${new Date(r.created_at).toLocaleString()}</span>
                </div>
                <p class="text-sm text-gray-700">${r.content}</p>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function postForumReply() {
    if (!currentTopicId) return;
    const content = document.getElementById('newReplyContent').value;

    if (!content) return showToast('Reply cannot be empty', 'error');

    try {
        const response = await fetch(`${API_BASE}/forum/topics/${currentTopicId}/replies`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ content })
        });
        if (response.ok) {
            showToast('Reply posted!', 'success');
            document.getElementById('newReplyContent').value = '';
            loadTopicReplies(currentTopicId);
            loadForumTopics(); // Update reply count in main list
        }
    } catch (err) {
        console.error(err);
    }
}

// PHASE 8: ENTERPRISE SECURITY & THEMES

async function initTheme() {
    try {
        const data = await authedGet('/user/theme');
        if (data && data.theme === 'dark') {
            document.documentElement.classList.add('dark');
            const icon = document.getElementById('themeIcon');
            if (icon) {
                icon.classList.remove('fa-moon');
                icon.classList.add('fa-sun');
            }
        }
    } catch (err) { console.error('Failed to init theme:', err); }
}

async function toggleDarkMode() {
    const isDark = document.documentElement.classList.toggle('dark');
    const theme = isDark ? 'dark' : 'light';
    const icon = document.getElementById('themeIcon');
    
    if (icon) {
        if (isDark) {
            icon.classList.remove('fa-moon');
            icon.classList.add('fa-sun');
        } else {
            icon.classList.remove('fa-sun');
            icon.classList.add('fa-moon');
        }
    }

    try {
        await fetch(`${API_BASE}/user/theme`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ theme })
        });
    } catch (err) { console.error('Failed to save theme:', err); }
}

async function loadLoginHistory() {
    try {
        const data = await authedGet('/security/login-history');
        const tbody = document.getElementById('loginHistoryTable');
        if (!tbody) return;

        tbody.innerHTML = data.history.map(log => `
            <tr class="hover:bg-gray-50 dark:hover:bg-gray-800/50">
                <td class="py-4">
                    <div class="flex items-center">
                        <i class="fas ${log.device_type === 'Mobile' ? 'fa-mobile-alt' : 'fa-desktop'} mr-3 text-gray-400"></i>
                        <div>
                            <p class="font-bold text-gray-800">${log.device_type}</p>
                            <p class="text-[10px] text-gray-500 truncate max-w-[150px]">${log.user_agent}</p>
                        </div>
                    </div>
                </td>
                <td class="py-4 font-mono text-xs text-gray-600">${log.ip_address}</td>
                <td class="py-4 text-xs text-gray-500">${new Date(log.created_at).toLocaleString()}</td>
                <td class="py-4">
                    <span class="px-2 py-0.5 rounded-full text-[10px] font-bold uppercase ${log.status === 'success' ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'}">
                        ${log.status}
                    </span>
                </td>
            </tr>
        `).join('') || '<tr><td colspan="4" class="py-8 text-center text-gray-500 italic">No login history found.</td></tr>';
    } catch (err) { console.error('Failed to load login history:', err); }
}

// UNIVERSAL SEARCH (Phase 7 Fix/Navigation)
let searchTimeout = null;
async function performUniversalSearch() {
    const input = document.getElementById('universalSearchInput');
    const resultsContainer = document.getElementById('universalSearchResults');
    const query = input.value.trim();

    if (!query) {
        resultsContainer.classList.add('hidden');
        return;
    }

    clearTimeout(searchTimeout);
    searchTimeout = setTimeout(async () => {
        try {
            const response = await fetch(`${API_BASE}/universal-search?q=${query}`, {
                headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
            });
            const data = await response.json();
            
            if (data.results.length === 0) {
                resultsContainer.innerHTML = '<div class="p-4 text-gray-500 text-sm">No matches found.</div>';
            } else {
                resultsContainer.innerHTML = data.results.map(res => `
                    <div onclick="handleSearchNavigation('${res.type}', ${res.id}, '${res.title.replace(/'/g, "\\'")}', '${(res.subtitle || '').replace(/'/g, "\\'")}')" class="p-3 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 cursor-pointer border-b last:border-0 flex items-center space-x-3">
                        <div class="w-8 h-8 rounded bg-gray-100 dark:bg-gray-800 flex items-center justify-center text-indigo-600">
                            <i class="fas ${getSearchIcon(res.type)}"></i>
                        </div>
                        <div class="flex-1">
                            <p class="text-sm font-bold text-gray-800">${res.title}</p>
                            <p class="text-[10px] text-gray-500">${res.subtitle}</p>
                        </div>
                        <span class="text-[9px] font-bold uppercase text-gray-400 border px-1.5 py-0.5 rounded">${res.type}</span>
                    </div>
                `).join('');
            }
            resultsContainer.classList.remove('hidden');
        } catch (err) { console.error(err); }
    }, 300);
}

function getSearchIcon(type) {
    switch(type) {
        case 'Book': return 'fa-book';
        case 'Subject': return 'fa-scroll';
        case 'Forum': return 'fa-comments';
        default: return 'fa-search';
    }
}

function handleSearchNavigation(type, id, title, subtitle) {
    document.getElementById('universalSearchResults').classList.add('hidden');
    document.getElementById('universalSearchInput').value = '';

    if (type === 'Book') {
        showSection('library');
    } else if (type === 'Subject') {
        showSection('curriculum');
        loadOBE(id);
    } else if (type === 'Forum') {
        showSection('forum');
        openTopicDetails(id, title, subtitle);
    }
}

// Update showSection to handle specific data loads
const originalShowSection = showSection;
showSection = function(sectionId) {
    originalShowSection(sectionId);
    if (sectionId === 'security') loadLoginHistory();
    if (sectionId === 'finance') loadFinanceDashboard();
    if (sectionId === 'exam-schedule') loadExamSchedule();
    if (sectionId === 'academic-calendar') loadAcademicCalendar();
    if (sectionId === 'learning') resetLearningBrowse();
};

function resetLearningBrowse() {
    const streamGrid = document.getElementById('streamGrid');
    const deptContainer = document.getElementById('deptContainer');
    const subjectContainer = document.getElementById('subjectContainer');
    const materialContainer = document.getElementById('materialContainer');
    const backBtn = document.getElementById('learningBackBtn');
    if (streamGrid) streamGrid.classList.remove('hidden');
    if (deptContainer) deptContainer.classList.add('hidden');
    if (subjectContainer) subjectContainer.classList.add('hidden');
    if (materialContainer) materialContainer.classList.add('hidden');
    if (backBtn) backBtn.classList.add('hidden');
}

async function loadAcademicCalendar() {
    const el = document.getElementById('academicCalendarList');
    if (!el) return;
    const days = document.getElementById('calendarDaysRange')?.value || 30;
    el.innerHTML = '<p class="text-gray-500 text-sm">Loading...</p>';
    try {
        const data = await authedGet(`/academic/calendar?days=${days}`);
        const items = data?.items || [];
        if (!items.length) {
            el.innerHTML = '<p class="text-gray-500 text-sm py-8 text-center">No upcoming events in this range. Assignments, exams, and holidays will appear here.</p>';
            return;
        }
        const typeColors = {
            class: 'bg-blue-100 text-blue-700',
            exam: 'bg-purple-100 text-purple-700',
            assignment: 'bg-amber-100 text-amber-700',
            holiday: 'bg-emerald-100 text-emerald-700',
            meeting: 'bg-rose-100 text-rose-700',
            other: 'bg-gray-100 text-gray-700',
        };
        el.innerHTML = items.map(ev => {
            const t = (ev.event_type || 'other').toLowerCase();
            const badge = typeColors[t] || typeColors.other;
            const when = ev.starts_at || '';
            const sub = ev.subject_name ? `<span class="text-xs text-gray-400"> · ${ev.subject_name}</span>` : '';
            return `
                <div class="bg-white p-4 rounded-xl border shadow-sm flex flex-col md:flex-row md:items-center md:justify-between gap-2">
                    <div>
                        <div class="flex items-center gap-2 mb-1">
                            <span class="text-[10px] font-bold uppercase px-2 py-0.5 rounded ${badge}">${t}</span>
                            <span class="text-[10px] text-gray-400 uppercase">${ev.source || 'calendar'}</span>
                        </div>
                        <p class="font-bold text-gray-800">${ev.title || 'Event'}</p>
                        <p class="text-sm text-gray-600">${ev.description || ''}${sub}</p>
                    </div>
                    <p class="text-sm font-mono text-indigo-600 whitespace-nowrap">${when}</p>
                </div>
            `;
        }).join('');
    } catch (err) {
        console.error(err);
        el.innerHTML = '<p class="text-red-500 text-sm">Failed to load calendar.</p>';
    }
}

// PHASE 10: SMART EXAM SCHEDULER & AUTOMATED WORKFLOW ENGINE

async function loadExamSchedule() {
    try {
        const data = await authedGet('/exams/schedule');
        const tbody = document.getElementById('examScheduleTable');
        if (!tbody) return;

        const today = new Date();
        let nextExamDate = null;

        tbody.innerHTML = data.schedule.map(ex => {
            const examDate = new Date(ex.exam_date);
            const isFuture = examDate > today;
            if (isFuture && (!nextExamDate || examDate < nextExamDate)) {
                nextExamDate = examDate;
            }

            return `
                <tr class="hover:bg-gray-50 transition">
                    <td class="p-4">
                        <p class="font-bold text-gray-800">${ex.subject_name}</p>
                        <p class="text-[10px] text-gray-400 uppercase font-bold">Sem ${ex.semester}</p>
                    </td>
                    <td class="p-4">
                        <span class="px-2 py-0.5 rounded text-[10px] font-bold uppercase ${ex.exam_type === 'Semester' ? 'bg-purple-100 text-purple-700' : 'bg-blue-100 text-blue-700'}">
                            ${ex.exam_type}
                        </span>
                    </td>
                    <td class="p-4 text-sm text-gray-600 font-medium">${ex.exam_date}</td>
                    <td class="p-4 text-sm text-gray-500">${ex.start_time} - ${ex.end_time}</td>
                    <td class="p-4 text-sm text-gray-500 font-mono">${ex.room_number || 'TBA'}</td>
                    <td class="p-4 text-right">
                        <span class="text-[10px] font-black uppercase tracking-widest ${isFuture ? 'text-amber-500' : 'text-emerald-500'}">
                            ${isFuture ? 'Upcoming' : 'Completed'}
                        </span>
                    </td>
                </tr>
            `;
        }).join('') || '<tr><td colspan="6" class="p-8 text-center text-gray-500 italic">No exams scheduled yet.</td></tr>';

        // Update countdown
        if (nextExamDate) {
            const diffTime = Math.abs(nextExamDate - today);
            const diffDays = Math.ceil(diffTime / (1000 * 60 * 60 * 24));
            document.getElementById('nextExamCountdown').textContent = `${diffDays} Days`;
        } else {
            document.getElementById('nextExamCountdown').textContent = 'None';
        }
    } catch (err) { console.error(err); }
}

async function triggerWorkflows() {
    try {
        const response = await fetch(`${API_BASE}/admin/workflows/run`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        if (response.ok) {
            showToast(data.message, 'success');
        }
    } catch (err) { console.error(err); }
}

// PHASE 9: FINANCE & CAMPUS STORE

async function loadFinanceDashboard() {
    loadWalletInfo();
    loadStoreItems();
}

async function loadWalletInfo() {
    try {
        const data = await authedGet('/wallet/balance');
        document.getElementById('walletBalance').textContent = data.balance.toFixed(2);
        
        const list = document.getElementById('walletTransactions');
        list.innerHTML = data.transactions.map(t => `
            <div class="flex justify-between items-center p-3 rounded-lg bg-gray-50 border border-gray-100">
                <div class="flex items-center">
                    <div class="w-8 h-8 rounded-full flex items-center justify-center mr-3 ${t.type === 'credit' ? 'bg-green-100 text-green-600' : 'bg-red-100 text-red-600'}">
                        <i class="fas ${t.type === 'credit' ? 'fa-arrow-down' : 'fa-arrow-up'} text-xs"></i>
                    </div>
                    <div>
                        <p class="text-xs font-bold text-gray-800">${t.description}</p>
                        <p class="text-[9px] text-gray-400">${new Date(t.created_at).toLocaleDateString()}</p>
                    </div>
                </div>
                <p class="text-sm font-black ${t.type === 'credit' ? 'text-green-600' : 'text-red-600'}">
                    ${t.type === 'credit' ? '+' : '-'}₹${t.amount}
                </p>
            </div>
        `).join('') || '<p class="text-center text-gray-500 text-xs py-4">No transactions yet.</p>';
    } catch (err) { console.error(err); }
}

async function submitWalletTopup() {
    const amount = document.getElementById('topupAmount').value;
    if (!amount || amount <= 0) return showToast('Please enter a valid amount', 'error');

    try {
        const response = await fetch(`${API_BASE}/wallet/topup`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ amount })
        });
        if (response.ok) {
            showToast(`₹${amount} added to wallet!`, 'success');
            closeModal('topupModal');
            loadWalletInfo();
        }
    } catch (err) { console.error(err); }
}

async function loadStoreItems(category = '') {
    try {
        const url = category ? `/store/items?category=${category}` : '/store/items';
        const data = await authedGet(url);
        const grid = document.getElementById('storeItemsGrid');
        
        grid.innerHTML = data.items.map(item => `
            <div class="bg-white p-5 rounded-2xl shadow-sm border hover:shadow-md transition group">
                <div class="h-40 bg-gray-100 rounded-xl mb-4 flex items-center justify-center relative overflow-hidden">
                    <i class="fas ${getStoreIcon(item.category)} text-4xl text-gray-300 group-hover:scale-110 transition duration-500"></i>
                    <div class="absolute top-2 right-2">
                        <span class="bg-white/80 backdrop-blur px-2 py-1 rounded-lg text-[10px] font-bold text-gray-600 border border-white">
                            Stock: ${item.stock}
                        </span>
                    </div>
                </div>
                <p class="text-[10px] font-black uppercase tracking-widest text-indigo-500 mb-1">${item.category}</p>
                <h4 class="font-bold text-gray-800 mb-1">${item.name}</h4>
                <p class="text-xs text-gray-500 mb-4 line-clamp-1">${item.description || 'No description available.'}</p>
                <div class="flex items-center justify-between">
                    <span class="text-lg font-black text-gray-800">₹${item.price}</span>
                    <button onclick="buyStoreItem(${item.id}, ${item.price}, '${item.name.replace(/'/g, "\\'")}')" 
                            class="p-2 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition shadow-sm">
                        <i class="fas fa-shopping-cart text-sm"></i>
                    </button>
                </div>
            </div>
        `).join('') || '<p class="col-span-full text-center py-12 text-gray-500">No items available in this category.</p>';
    } catch (err) { console.error(err); }
}

function getStoreIcon(category) {
    switch(category) {
        case 'Book': return 'fa-book-open';
        case 'Merchandise': return 'fa-tshirt';
        case 'Stationery': return 'fa-pen-fancy';
        default: return 'fa-box';
    }
}

async function buyStoreItem(itemId, price, name) {
    if (!confirm(`Confirm purchase of "${name}" for ₹${price}?`)) return;

    try {
        const response = await fetch(`${API_BASE}/store/order`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                items: [{ id: itemId, quantity: 1, price: price }],
                total_amount: price,
                payment_method: 'wallet'
            })
        });
        const data = await response.json();
        if (response.ok) {
            showToast('Purchase successful!', 'success');
            loadFinanceDashboard();
        } else {
            showToast(data.message, 'error');
        }
    } catch (err) { console.error(err); }
}
