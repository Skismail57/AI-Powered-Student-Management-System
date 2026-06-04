// engagement.js
const API_BASE = '/api/engagement';

function loadEngagement() {
    const classId = document.getElementById('classId').value;
    if (!classId) return;
    fetch(`${API_BASE}/${classId}`)
        .then(res => res.json())
        .then(data => {
            const list = document.getElementById('analyticsList');
            if (!Array.isArray(data) || data.length === 0) {
                list.innerHTML = '<p>No analytics found for this class.</p>';
                return;
            }
            list.innerHTML = '<table><tr><th>Date</th><th>Faculty</th><th>Quiz Participation</th><th>Attendance Interaction</th><th>Notes</th></tr>' +
                data.map(r => `<tr><td>${r.date}</td><td>${r.faculty_id}</td><td>${r.quiz_participation}%</td><td>${r.attendance_interaction}%</td><td>${r.notes}</td></tr>`).join('') + '</table>';
        })
        .catch(() => {
            document.getElementById('analyticsList').innerHTML = '<p>Error loading analytics.</p>';
        });
}

function submitEngagement(event) {
    event.preventDefault();
    const payload = {
        class_id: document.getElementById('formClassId').value,
        faculty_id: document.getElementById('facultyId').value,
        date: document.getElementById('date').value,
        quiz_participation: document.getElementById('quizParticipation').value,
        attendance_interaction: document.getElementById('attendanceInteraction').value,
        notes: document.getElementById('notes').value
    };
    fetch(API_BASE, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
    })
    .then(res => res.json())
    .then(() => {
        alert('Engagement analytics submitted!');
        loadEngagement();
        document.getElementById('engagementForm').reset();
    })
    .catch(() => alert('Error submitting analytics.'));
}
