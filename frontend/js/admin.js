
const API_BASE = 'http://localhost:5000';
const socket = io(API_BASE);
let adminChart;

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
    document.querySelectorAll('.content-section').forEach(sec => sec.classList.add('hidden'));
    document.querySelectorAll('.sidebar-item').forEach(l => l.classList.remove('active'));
    
    const target = document.getElementById(sectionId);
    if (target) {
        target.classList.remove('hidden');
    }
    
    const sidebarLink = document.querySelector(`a[onclick*="showSection('${sectionId}')"]`);
    if (sidebarLink) {
        sidebarLink.classList.add('active');
    }

    if (sectionId === 'analytics-advanced') loadInstitutionComparison();
}

async function loadInstitutionComparison() {
    try {
        const data = await authedGet('/admin/institution-comparison');
        const grid = document.getElementById('comparisonList');
        if (!grid) return;

        grid.innerHTML = data.comparison.map(dept => `
            <div class="bg-white p-6 rounded-xl border shadow-sm">
                <h4 class="font-bold text-gray-800 mb-2">${dept.department}</h4>
                <div class="flex justify-between text-sm mb-1">
                    <span class="text-gray-500">Avg Attendance</span>
                    <span class="font-bold text-blue-600">${dept.avg_attendance?.toFixed(1) || 0}%</span>
                </div>
                <div class="w-full bg-gray-100 rounded-full h-2 mb-4">
                    <div class="bg-blue-600 h-2 rounded-full" style="width: ${dept.avg_attendance || 0}%"></div>
                </div>
                <div class="flex justify-between text-xs text-gray-400 font-bold uppercase">
                    <span>${dept.student_count} Students</span>
                </div>
            </div>
        `).join('') || '<p class="text-center text-gray-500 py-12 col-span-full">No comparison data available.</p>';
        
        // Update Chart
        const ctx = document.getElementById('comparisonChart');
        if (ctx) {
            new Chart(ctx, {
                type: 'bar',
                data: {
                    labels: data.comparison.map(d => d.department),
                    datasets: [{
                        label: 'Avg Attendance %',
                        data: data.comparison.map(d => d.avg_attendance),
                        backgroundColor: '#3b82f6',
                        borderRadius: 8
                    }]
                },
                options: { responsive: true, maintainAspectRatio: false }
            });
        }
    } catch (err) { console.error(err); }
}

document.addEventListener('DOMContentLoaded', () => {
    const user = JSON.parse(localStorage.getItem('user'));
    const token = localStorage.getItem('token');
    
    if (!token) {
        window.location.href = 'login.html';
        return;
    }

    document.getElementById('welcomeMsg').textContent = `Welcome, ${user.name}!`;

    loadDashboard();
    loadStudents();
    loadPayments();
    loadUsers();

    document.getElementById('searchStudent').addEventListener('input', loadStudents);
    document.getElementById('logoutBtn').addEventListener('click', () => {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        window.location.href = 'login.html';
    });

    socket.on('dashboard_update', loadDashboard);
});

async function loadDashboard() {
    try {
        const [statsData, dashboardData] = await Promise.all([
            authedGet('/admin/dashboard-stats'),
            authedGet('/dashboard')
        ]);
        
        document.getElementById('totalStudentsStat').textContent = statsData.total_students || 0;
        document.getElementById('avgAttendanceStat').textContent = `${(statsData.avg_attendance || 0).toFixed(1)}%`;
        document.getElementById('atRiskStudentsStat').textContent = statsData.at_risk_count || 0;
        document.getElementById('totalPaymentsStat').textContent = `₹${statsData.total_payments || 0}`;
        
        if (dashboardData && dashboardData.chart_data) {
            initChart(dashboardData.chart_data);
        }
    } catch (err) {
        console.error('Failed to load admin stats:', err);
    }
}

function initChart(chartData) {
    const ctx = document.getElementById('attendanceTrendChart');
    if (ctx) {
        if (adminChart) adminChart.destroy();
        adminChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: chartData.labels,
                datasets: [{
                    label: 'Attendance %',
                    data: chartData.attendance,
                    backgroundColor: 'rgba(79, 70, 229, 0.6)',
                    borderRadius: 8
                }]
            },
            options: { 
                responsive: true, 
                maintainAspectRatio: false,
                plugins: { 
                    legend: { display: false } 
                }, 
                scales: { 
                    y: { 
                        beginAtZero: true, 
                        max: 100,
                        ticks: { stepSize: 20 }
                    } 
                } 
            }
        });
    }
}

async function loadStudents() {
    try {
        const search = document.getElementById('searchStudent').value;
        const students = await authedGet(`/students?search=${search}`);
        const container = document.getElementById('studentsList');
        if (!container) return;

        container.innerHTML = students.map(student => `
            <div class="flex items-center justify-between p-4 bg-gray-50 rounded-xl hover:bg-gray-100 transition">
                <div>
                    <h3 class="font-bold text-gray-800">${student.name}</h3>
                    <p class="text-xs text-gray-500">Attendance: ${student.attendance}% | Study: ${student.study_hours}h | Sleep: ${student.sleep_hours}h</p>
                </div>
                <div class="flex gap-2">
                    <button class="p-2 text-blue-600 hover:bg-blue-50 rounded-lg transition" onclick="editStudent(${student.id}, '${student.name}', ${student.attendance}, ${student.study_hours}, ${student.sleep_hours})">
                        <i class="fas fa-edit"></i>
                    </button>
                    <button class="p-2 text-red-600 hover:bg-red-50 rounded-lg transition" onclick="deleteStudent(${student.id})">
                        <i class="fas fa-trash"></i>
                    </button>
                </div>
            </div>
        `).join('') || '<p class="text-center text-gray-400 py-4">No students found.</p>';
    } catch (err) {
        console.error(err);
    }
}

async function loadPayments() {
    try {
        const payments = await authedGet('/payments');
        const container = document.getElementById('paymentsList');
        if (!container) return;

        container.innerHTML = payments.map(payment => `
            <div class="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                <div>
                    <h3 class="font-bold text-gray-800">Payment #${payment.id}</h3>
                    <p class="text-xs text-gray-500">Student ID: ${payment.student_id} | Status: <span class="text-emerald-600 font-bold uppercase">${payment.status}</span></p>
                </div>
                <div class="text-right">
                    <p class="font-black text-gray-800">₹${payment.amount}</p>
                    <p class="text-[10px] text-gray-400">${new Date(payment.created_at).toLocaleDateString()}</p>
                </div>
            </div>
        `).join('') || '<p class="text-center text-gray-400 py-4">No payments found.</p>';
    } catch (err) {
        console.error(err);
    }
}

async function loadUsers() {
    try {
        const users = await authedGet('/admin/users');
        const container = document.getElementById('usersList');
        if (!container) return;

        container.innerHTML = users.map(user => `
            <div class="flex items-center justify-between p-4 bg-gray-50 rounded-xl">
                <div class="flex items-center gap-3">
                    <div class="w-10 h-10 rounded-full bg-indigo-100 flex items-center justify-center text-indigo-600 font-bold">
                        ${user.name.charAt(0)}
                    </div>
                    <div>
                        <h3 class="font-bold text-gray-800">${user.name}</h3>
                        <p class="text-xs text-gray-500">${user.role.toUpperCase()} | ${user.mobile}</p>
                    </div>
                </div>
                <button class="text-rose-600 text-sm font-bold hover:underline" onclick="deleteUser(${user.id})">Revoke</button>
            </div>
        `).join('') || '<p class="text-center text-gray-400 py-4">No users found.</p>';
    } catch (err) {
        console.error(err);
    }
}

async function addStudent() {
    // This should ideally open a modal, but using prompt for simplicity as per original code
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
        showToast('Student added successfully!', 'success');
    } catch (err) {
        showToast('Failed to add student!', 'error');
    }
}

async function editStudent(id, name, attendance, study_hours, sleep_hours) {
    const newName = prompt('Enter new name:', name);
    if (newName === null) return;
    
    const newAtt = prompt('Enter attendance %:', attendance);
    const newStudy = prompt('Enter study hours:', study_hours);
    const newSleep = prompt('Enter sleep hours:', sleep_hours);
    
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
    if (!confirm('Are you sure you want to delete this student?')) return;
    try {
        await fetch(`${API_BASE}/students/${id}`, {
            method: 'DELETE',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        loadStudents();
        showToast('Student deleted', 'success');
    } catch (err) {
        showToast('Delete failed', 'error');
    }
}

async function runCloudBackup() {
    const statusEl = document.getElementById('backupStatus');
    statusEl.innerHTML = '<i class="fas fa-spinner fa-spin mr-2"></i> Initializing cloud backup...';
    
    try {
        const response = await fetch(`${API_BASE}/admin/cloud-backup`, {
            method: 'POST',
            headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
        });
        const data = await response.json();
        if (response.ok) {
            statusEl.innerHTML = `<span class="text-emerald-600 font-bold"><i class="fas fa-check-circle mr-2"></i> Backup Successful!</span><br>ID: ${data.backup_id} | Size: ${data.size_mb} MB`;
            showToast('Cloud backup complete', 'success');
        }
    } catch (err) {
        statusEl.innerHTML = '<span class="text-rose-600">Backup failed.</span>';
        console.error(err);
    }
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
