
const API_BASE = 'http://localhost:5000';
const socket = io(API_BASE);
let facultyChart;

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

function showSection(sectionId) {
    document.querySelectorAll('.content-section').forEach(sec => {
        sec.classList.add('hidden');
        sec.style.display = ''; // Reset inline style if any
    });
    document.querySelectorAll('.sidebar-item').forEach(l => l.classList.remove('active'));
    
    const target = document.getElementById(sectionId);
    if (target) {
        target.classList.remove('hidden');
    }
    
    const sidebarLink = document.querySelector(`a[onclick="showSection('${sectionId}')"]`);
    if (sidebarLink) {
        sidebarLink.classList.add('active');
    }

    // Reload data
    if (sectionId === 'research') loadResearch();
    if (sectionId === 'appointments') loadAppointments();
    if (sectionId === 'lesson-planner') loadLessonPlans();
    if (sectionId === 'analytics') { loadTopicAnalytics(); loadDashboard(); }
    if (sectionId === 'voice-notes') loadVoiceNotes();
    if (sectionId === 'placements-admin') loadMockInterviews();
    if (sectionId === 'flashcards-admin') loadFlashcards();
}

document.addEventListener('DOMContentLoaded', () => {
    const user = JSON.parse(localStorage.getItem('user'));
    const token = localStorage.getItem('token');
    
    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    document.getElementById('facultyName').textContent = user.name;

    document.getElementById('logoutBtn').addEventListener('click', () => {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = 'login.html';
    });

    loadDashboard();
    loadStudents();
    loadAttendanceMarking();
    loadNotes();
    loadAnnouncements();
    initForms();
    loadLessonPlans();
    loadTopicAnalytics();
    loadVoiceNotes();
    initPhase3Listeners();

    document.getElementById('searchStudent').addEventListener('input', loadStudents);
    socket.on('attendance_update', loadDashboard);
    socket.on('dashboard_update', loadDashboard);
});

async function loadDashboard() {
    try {
        const response = await fetch(`${API_BASE}/dashboard`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        
        document.getElementById('totalStudents').textContent = data.total_students;
        document.getElementById('avgAttendance').textContent = `${data.avg_attendance}%`;
        
        initChart(data.chart_data);
    } catch (err) {
        console.error(err);
    }
}

function initChart(chartData) {
    const ctx = document.getElementById('facultyChart');
    if (ctx) {
        if (facultyChart) facultyChart.destroy();
        facultyChart = new Chart(ctx, {
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
}

async function loadStudents() {
    try {
        const search = document.getElementById('searchStudent').value;
        const response = await fetch(`${API_BASE}/students?search=${search}`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const students = await response.json();
        const container = document.getElementById('studentsList');
        container.innerHTML = students.map(student => `
            <div class="student-item">
                <div>
                    <h3>${student.name}</h3>
                    <p>Attendance: ${student.attendance}% | Study: ${student.study_hours}h | Sleep: ${student.sleep_hours}h</p>
                </div>
                <div>
                    <button class="btn-edit" onclick="editStudent(${student.id}, '${student.name}', ${student.attendance}, ${student.study_hours}, ${student.sleep_hours})">Edit</button>
                    <button class="btn-delete" onclick="deleteStudent(${student.id})">Delete</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function loadAttendanceMarking() {
    try {
        const response = await fetch(`${API_BASE}/students`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const students = await response.json();
        const container = document.getElementById('attendanceMarking');
        container.innerHTML = students.map(student => `
            <div class="student-item">
                <span>${student.name}</span>
                <div>
                    <button onclick="markAttendance(${student.id}, 'present')" class="btn-edit">Present</button>
                    <button onclick="markAttendance(${student.id}, 'absent')" class="btn-delete">Absent</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
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

function initForms() {
    document.getElementById('addStudentBtn').addEventListener('click', async () => {
        const name = prompt('Enter student name:');
        if (!name) return;
        
        try {
            await fetch(`${API_BASE}/students`, {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${localStorage.getItem('token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ name, attendance: 0, study_hours: 0, sleep_hours: 0 })
            });
            loadStudents();
            loadAttendanceMarking();
            showToast('Student added!', 'success');
        } catch (err) {
            showToast('Failed to add student!', 'error');
        }
    });

    document.getElementById('uploadNotesForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData();
        formData.append('course', document.getElementById('courseName').value);
        formData.append('file', document.getElementById('noteFile').files[0]);
        
        try {
            await fetch(`${API_BASE}/notes`, {
                method: 'POST',
                headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` },
                body: formData
            });
            loadNotes();
            showToast('Note uploaded!', 'success');
            document.getElementById('uploadNotesForm').reset();
        } catch (err) {
            showToast('Upload failed!', 'error');
        }
    });

    document.getElementById('announcementForm').addEventListener('submit', async (e) => {
        e.preventDefault();
        try {
            await fetch(`${API_BASE}/announcements`, {
                method: 'POST',
                headers: { 
                    'Authorization': `Bearer ${localStorage.getItem('token')}`,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ message: document.getElementById('announcementText').value })
            });
            loadAnnouncements();
            showToast('Announcement posted!', 'success');
            document.getElementById('announcementForm').reset();
        } catch (err) {
            showToast('Failed to post!', 'error');
        }
    });
}

async function editStudent(id, name, attendance, study_hours, sleep_hours) {
    const newName = prompt('Enter new name:', name);
    const newAtt = prompt('Enter attendance %:', attendance);
    const newStudy = prompt('Enter study hours:', study_hours);
    const newSleep = prompt('Enter sleep hours:', sleep_hours);
    
    if (!newName) return;
    
    try {
        await fetch(`${API_BASE}/students/${id}`, {
            method: 'PUT',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                name: newName, 
                attendance: parseFloat(newAtt), 
                study_hours: parseFloat(newStudy), 
                sleep_hours: parseFloat(newSleep) 
            })
        });
        loadStudents();
        showToast('Student updated!', 'success');
    } catch (err) {
        showToast('Update failed!', 'error');
    }
}

async function deleteStudent(id) {
    if (!confirm('Delete this student?')) return;
    
    try {
        await fetch(`${API_BASE}/students/${id}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        loadStudents();
        loadAttendanceMarking();
        showToast('Student deleted!', 'success');
    } catch (err) {
        showToast('Delete failed!', 'error');
    }
}

async function markAttendance(studentId, status) {
    try {
        await fetch(`${API_BASE}/attendance`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ 
                student_id: studentId, 
                date: new Date().toISOString().split('T')[0], 
                status, 
                notes: '' 
            })
        });
        showToast(`Marked as ${status}!`, 'success');
    } catch (err) {
        showToast('Attendance failed!', 'error');
    }
}

// PHASE 3 FACULTY LOGIC

async function loadLessonPlans() {
    try {
        const response = await fetch(`${API_BASE}/faculty/lesson-plans`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const grid = document.getElementById('lessonPlansGrid');
        if (!grid) return;

        grid.innerHTML = data.items.map(plan => `
            <div class="bg-white p-6 rounded-lg shadow-md border-l-4 border-blue-500">
                <div class="flex justify-between items-start mb-2">
                    <span class="text-xs font-bold text-blue-600 bg-blue-50 px-2 py-1 rounded">Week ${plan.week_number}</span>
                    <span class="text-xs uppercase font-bold ${plan.status === 'completed' ? 'text-green-600' : 'text-orange-600'}">${plan.status}</span>
                </div>
                <h4 class="font-bold text-lg mb-1">${plan.topic}</h4>
                <p class="text-sm text-gray-500 mb-3">${plan.subject_name}</p>
                <div class="space-y-1">
                    <p class="text-xs font-bold text-gray-400 uppercase">Learning Outcomes:</p>
                    <ul class="text-xs text-gray-600 list-disc list-inside">
                        ${plan.learning_outcomes.split(',').map(o => `<li>${o.trim()}</li>`).join('')}
                    </ul>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function addLessonPlan() {
    const subject_id = document.getElementById('lessonPlanSubject').value;
    const topic = document.getElementById('lessonPlanTopic').value;
    const week_number = document.getElementById('lessonPlanWeek').value;
    const learning_outcomes = document.getElementById('lessonPlanOutcomes').value;

    if (!topic) return showToast('Topic is required', 'error');

    try {
        const response = await fetch(`${API_BASE}/faculty/lesson-plans`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ subject_id, topic, week_number, learning_outcomes })
        });
        if (response.ok) {
            showToast('Lesson plan saved!', 'success');
            closeModal('newLessonPlanModal');
            loadLessonPlans();
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadTopicAnalytics() {
    try {
        const response = await fetch(`${API_BASE}/faculty/topic-analytics`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('topicAnalyticsList');
        if (!list) return;

        list.innerHTML = data.items.map(topic => `
            <div class="p-4 bg-gray-50 rounded-lg border border-gray-100">
                <div class="flex justify-between items-center mb-2">
                    <h4 class="font-bold text-gray-800">${topic.topic_name}</h4>
                    <span class="text-xs font-bold ${topic.fail_rate > 30 ? 'text-red-600' : 'text-green-600'}">
                        ${topic.fail_rate}% Struggle Rate
                    </span>
                </div>
                <div class="w-full bg-gray-200 rounded-full h-2">
                    <div class="bg-blue-600 h-2 rounded-full" style="width: ${topic.avg_score}%"></div>
                </div>
                <div class="flex justify-between mt-1">
                    <span class="text-[10px] text-gray-400">Average Score</span>
                    <span class="text-[10px] font-bold text-gray-600">${topic.avg_score}%</span>
                </div>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function generateAIQuestions() {
    const topic = document.getElementById('aiGenTopic').value;
    const difficulty = document.getElementById('aiGenDifficulty').value;

    if (!topic) return showToast('Please enter a topic', 'error');

    const output = document.getElementById('aiGeneratedOutput');
    output.innerHTML = '<div class="text-center py-20"><i class="fas fa-robot fa-spin text-4xl text-indigo-500 mb-4"></i><p>AI is thinking...</p></div>';

    try {
        const response = await fetch(`${API_BASE}/faculty/ai-generate-assignment`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ topic, difficulty })
        });
        const data = await response.json();
        
        output.innerHTML = `
            <div class="bg-indigo-50 p-4 rounded-lg mb-6 border border-indigo-100">
                <div class="flex justify-between items-center mb-2">
                    <h4 class="font-bold text-indigo-800">Topic: ${data.topic}</h4>
                    <span class="text-xs font-bold text-indigo-600 uppercase">${data.difficulty}</span>
                </div>
                <p class="text-xs text-indigo-500">Suggested Due Date: ${data.suggested_due_date}</p>
            </div>
            <div class="space-y-4">
                ${data.generated_questions.map((q, i) => `
                    <div class="p-4 border rounded-lg hover:border-indigo-300 transition">
                        <div class="flex justify-between mb-2">
                            <span class="text-xs font-bold text-gray-400 uppercase">Question ${i+1}</span>
                            <span class="text-[10px] bg-gray-100 px-2 py-0.5 rounded text-gray-500">${q.type}</span>
                        </div>
                        <p class="text-gray-800 font-medium">${q.q}</p>
                    </div>
                `).join('')}
            </div>
            <button class="w-full mt-6 py-3 bg-indigo-600 text-white rounded-lg font-bold shadow-lg" onclick="showToast('Assignment published to students!', 'success')">
                Publish Assignment
            </button>
        `;
    } catch (err) {
        output.innerHTML = '<p class="text-red-500 text-center py-20">AI Generation failed. Please try again.</p>';
    }
}

async function loadVoiceNotes() {
    try {
        const data = await authedGet('/academic/lectures');
        const grid = document.getElementById('voiceNotesGrid');
        if (!grid) return;

        grid.innerHTML = data.items.map(note => `
            <div class="bg-white p-4 rounded-lg shadow-md border hover:border-red-500 transition">
                <div class="flex items-center space-x-3 mb-4">
                    <div class="w-10 h-10 bg-red-100 rounded-full flex items-center justify-center">
                        <i class="fas fa-play text-red-600"></i>
                    </div>
                    <div>
                        <h4 class="font-bold text-gray-800">${note.title}</h4>
                        <p class="text-xs text-gray-500">${new Date(note.recorded_at).toLocaleDateString()}</p>
                    </div>
                </div>
                <div class="bg-gray-100 h-1 rounded-full mb-4">
                    <div class="bg-red-500 h-1 rounded-full w-1/3"></div>
                </div>
                <a href="${note.video_url}" target="_blank" class="text-xs font-bold text-red-600 hover:text-red-800 uppercase flex items-center">
                    <i class="fas fa-external-link-alt mr-1"></i> View Recording
                </a>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-12 col-span-full">No lecture recordings found.</p>';
    } catch (err) {
        console.error(err);
    }
}

async function uploadVoiceNote() {
    const payload = {
        subject_id: document.getElementById('voiceNoteSubject').value,
        title: document.getElementById('voiceNoteTitle').value,
        video_url: document.getElementById('voiceNoteUrl').value,
        duration_minutes: 60 // Default
    };

    if (!payload.title || !payload.video_url) return showToast('Title and URL required', 'error');

    try {
        const response = await fetch(`${API_BASE}/academic/lectures`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            showToast('Lecture recording added!', 'success');
            closeModal('uploadVoiceModal');
            loadVoiceNotes();
        }
    } catch (err) {
        console.error(err);
    }
}

// ADVANCED PLACEMENT & FLASHCARDS
async function scheduleMockInterview() {
    const payload = {
        student_id: document.getElementById('mockStudentId').value,
        interviewer_name: document.getElementById('mockInterviewer').value,
        scheduled_at: document.getElementById('mockDate').value,
        status: 'scheduled'
    };

    try {
        const response = await fetch(`${API_BASE}/placement/mock-interviews`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            showToast('Mock interview scheduled!', 'success');
        }
    } catch (err) { console.error(err); }
}

async function addFlashcard() {
    const payload = {
        subject_id: document.getElementById('flashSubjectId').value,
        question: document.getElementById('flashQuestion').value,
        answer: document.getElementById('flashAnswer').value
    };

    try {
        const response = await fetch(`${API_BASE}/academic/flashcards`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            showToast('Flashcard added!', 'success');
        }
    } catch (err) { console.error(err); }
}

// AUTOMATED GRADING
function openGradeModal(submissionId) {
    document.getElementById('gradeSubmissionId').value = submissionId;
    openModal('gradeSubmissionModal');
}

async function submitGrade() {
    const submission_id = document.getElementById('gradeSubmissionId').value;
    const score = document.getElementById('gradeScore').value;
    const feedback = document.getElementById('gradeFeedback').value;

    if (!score) return showToast('Score is required', 'error');

    try {
        const response = await fetch(`${API_BASE}/faculty/grade-submission`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ submission_id, score, feedback })
        });
        if (response.ok) {
            showToast('Submission graded!', 'success');
            closeModal('gradeSubmissionModal');
            loadFacultyAssignments(); // Refresh list
        }
    } catch (err) {
        console.error(err);
    }
}

async function loadFacultyAssignments() {
    try {
        const response = await fetch(`${API_BASE}/faculty/assignments`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const grid = document.getElementById('facultyAssignmentsList');
        if (!grid) return;

        grid.innerHTML = data.items.map(a => `
            <div class="bg-white p-6 rounded-lg shadow-md border-t-4 border-indigo-500">
                <div class="flex justify-between items-start mb-4">
                    <h4 class="font-bold text-lg">${a.title}</h4>
                    <span class="text-xs text-gray-400 font-bold uppercase">${a.subject_name}</span>
                </div>
                <div class="space-y-3 mb-6">
                    <div class="flex justify-between text-sm">
                        <span class="text-gray-500">Total Submissions</span>
                        <span class="font-bold text-indigo-600">${a.submission_count}</span>
                    </div>
                    <div class="flex justify-between text-sm">
                        <span class="text-gray-500">Pending Grading</span>
                        <span class="font-bold text-orange-600">${a.pending_grading}</span>
                    </div>
                </div>
                <button onclick="viewSubmissions(${a.id})" class="w-full py-2 bg-indigo-600 text-white rounded font-bold hover:bg-indigo-700 transition">
                    Manage Submissions
                </button>
            </div>
        `).join('');
    } catch (err) {
        console.error(err);
    }
}

async function viewSubmissions(assignmentId) {
    showToast('Loading submissions...', 'info');
    // This would typically open another view/modal with the list of student submissions
    // For demo purposes, we'll simulate opening a grade modal for the first pending one if any
}

function initPhase3Listeners() {
    // Modal controls are already handled by onclick in HTML
}

function openModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.style.display = 'flex';
}

function closeModal(id) {
    const modal = document.getElementById(id);
    if (modal) modal.style.display = 'none';
}

// RESEARCH PORTAL
async function loadResearch() {
    try {
        const response = await fetch(`${API_BASE}/faculty/research`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('researchList');
        if (!list) return;
        
        list.innerHTML = data.items.map(r => `
            <div class="bg-white p-6 rounded-lg shadow-sm border border-l-4 border-indigo-500">
                <div class="flex justify-between items-start mb-2">
                    <h4 class="font-bold text-lg text-gray-800">${r.title}</h4>
                    <span class="bg-indigo-100 text-indigo-700 text-[10px] font-bold px-2 py-1 rounded uppercase">${r.publication_type}</span>
                </div>
                <p class="text-sm text-gray-500 italic mb-4">${r.journal_name} • ${new Date(r.publication_date).toLocaleDateString()}</p>
                ${r.url ? `
                    <a href="${r.url}" target="_blank" class="text-xs text-indigo-600 font-bold hover:underline">
                        <i class="fas fa-external-link-alt mr-1"></i> View Publication
                    </a>
                ` : ''}
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-12 col-span-full">No publications recorded yet.</p>';
    } catch (err) { console.error(err); }
}

async function submitResearch() {
    const payload = {
        title: document.getElementById('researchTitle').value,
        type: document.getElementById('researchType').value,
        journal: document.getElementById('researchJournal').value,
        date: document.getElementById('researchDate').value,
        url: document.getElementById('researchUrl').value
    };

    if (!payload.title || !payload.date) return showToast('Title and Date are required', 'error');

    try {
        const response = await fetch(`${API_BASE}/faculty/research`, {
            method: 'POST',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });
        if (response.ok) {
            showToast('Publication added!', 'success');
            closeModal('addResearchModal');
            loadResearch();
        }
    } catch (err) { console.error(err); }
}

// APPOINTMENTS
async function loadAppointments() {
    try {
        const response = await fetch(`${API_BASE}/appointments`, {
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        const list = document.getElementById('appointmentsList');
        if (!list) return;
        
        list.innerHTML = data.items.map(a => `
            <tr class="hover:bg-gray-50">
                <td class="p-4 border-b font-medium text-gray-800">${a.parent_name}</td>
                <td class="p-4 border-b text-gray-500">${a.student_name}</td>
                <td class="p-4 border-b text-gray-500">${a.purpose}</td>
                <td class="p-4 border-b text-gray-500">${new Date(a.preferred_date).toLocaleDateString()}</td>
                <td class="p-4 border-b">
                    <span class="px-2 py-1 rounded-full text-[10px] font-bold uppercase ${
                        a.status === 'approved' ? 'bg-green-100 text-green-700' : 
                        (a.status === 'pending' ? 'bg-yellow-100 text-yellow-700' : 'bg-gray-100 text-gray-700')
                    }">${a.status}</span>
                </td>
                <td class="p-4 border-b">
                    ${a.status === 'pending' ? `
                        <div class="flex space-x-2">
                            <button onclick="updateAppStatus(${a.id}, 'approved')" class="text-xs bg-green-600 text-white px-2 py-1 rounded">Approve</button>
                            <button onclick="updateAppStatus(${a.id}, 'cancelled')" class="text-xs bg-red-600 text-white px-2 py-1 rounded">Cancel</button>
                        </div>
                    ` : '-'}
                </td>
            </tr>
        `).join('') || '<tr><td colspan="6" class="p-8 text-center text-gray-500 italic">No appointment requests found.</td></tr>';
    } catch (err) { console.error(err); }
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `fixed bottom-4 right-4 px-6 py-3 rounded-lg shadow-lg z-[2000] text-white font-bold transition-all transform translate-y-0 ${
        type === 'success' ? 'bg-green-500' : type === 'error' ? 'bg-red-500' : 'bg-blue-500'
    }`;
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateY(20px)';
        setTimeout(() => toast.remove(), 500);
    }, 3000);
}

async function updateAppStatus(id, status) {
    const remarks = prompt('Enter any remarks (optional):');
    try {
        const response = await fetch(`${API_BASE}/appointments/${id}/status`, {
            method: 'PUT',
            headers: { 
                'Authorization': `Bearer ${localStorage.getItem('token')}`,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ status, remarks })
        });
        if (response.ok) {
            showToast(`Appointment ${status}!`, 'success');
            loadAppointments();
        }
    } catch (err) { console.error(err); }
}
