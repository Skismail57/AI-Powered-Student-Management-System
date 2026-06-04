
self.addEventListener('install', e => {
    e.waitUntil(
        caches.open('studentms-v1').then(cache => {
            return cache.addAll(['login.html', 'student.html', 'faculty.html', 'admin.html', 'css/style.css']);
        })
    );
});

self.addEventListener('fetch', e => {
    e.respondWith(
        caches.match(e.request).then(response => {
            return response || fetch(e.request);
        })
    );
});
