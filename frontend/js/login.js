
const API_BASE = 'http://localhost:5000';

document.addEventListener('DOMContentLoaded', () => {
    const loginForm = document.getElementById('loginForm');
    const registerForm = document.getElementById('registerForm');
    const showRegister = document.getElementById('showRegister');
    const showLogin = document.getElementById('showLogin');
    const loginSection = document.getElementById('loginSection');
    const registerSection = document.getElementById('registerSection');

    if (showRegister && loginSection && registerSection) {
        showRegister.addEventListener('click', (e) => {
            e.preventDefault();
            loginSection.classList.add('hidden');
            registerSection.classList.remove('hidden');
        });
    }

    if (showLogin && loginSection && registerSection) {
        showLogin.addEventListener('click', (e) => {
            e.preventDefault();
            registerSection.classList.add('hidden');
            loginSection.classList.remove('hidden');
        });
    }

    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const mobileInput = document.getElementById('mobile');
            const passwordInput = document.getElementById('password');
            
            if (!mobileInput || !passwordInput) {
                showToast('Form inputs missing!', 'error');
                return;
            }

            try {
                const response = await fetch(`${API_BASE}/login`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        mobile: mobileInput.value,
                        password: passwordInput.value
                    })
                });
                const data = await response.json();
                if (response.ok) {
                    localStorage.setItem('token', data.token);
                    localStorage.setItem('user', JSON.stringify(data.user));
                    if (data.user.role === 'student') {
                        window.location.href = 'student.html';
                    } else if (data.user.role === 'faculty') {
                        window.location.href = 'faculty.html';
                    } else if (data.user.role === 'parent') {
                        window.location.href = 'parent.html';
                    } else if (data.user.role === 'admin') {
                        window.location.href = 'admin.html';
                    } else {
                        showToast('Unknown user role!', 'error');
                    }
                } else {
                    showToast(data.message || 'Login failed!', 'error');
                }
            } catch (err) {
                console.error(err);
                showToast('Login failed! Is the backend running?', 'error');
            }
        });
    }

    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            try {
                const response = await fetch(`${API_BASE}/register`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        name: document.getElementById('regName').value,
                        role: document.getElementById('regRole').value,
                        mobile: document.getElementById('regMobile').value,
                        password: document.getElementById('regPassword').value
                    })
                });
                if (response.ok) {
                    showToast('Registered successfully! Please login.', 'success');
                    if (loginSection && registerSection) {
                        registerSection.classList.add('hidden');
                        loginSection.classList.remove('hidden');
                    }
                } else {
                    const data = await response.json();
                    showToast(data.message || 'Registration failed!', 'error');
                }
            } catch (err) {
                showToast('Registration failed!', 'error');
            }
        });
    }
});

function showToast(message, type) {
    const toast = document.createElement('div');
    toast.textContent = message;
    toast.style.position = 'fixed';
    toast.style.top = '20px';
    toast.style.right = '20px';
    toast.style.padding = '15px 25px';
    toast.style.borderRadius = '8px';
    toast.style.color = 'white';
    toast.style.fontWeight = '600';
    toast.style.zIndex = '2000';
    if (type === 'success') toast.style.background = '#4caf50';
    if (type === 'error') toast.style.background = '#f44336';
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}
