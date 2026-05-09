// 현재 시간 표시
function updateTime() {
    const el = document.getElementById('current-time');
    if (!el) return;
    const now = new Date();
    el.textContent = now.toLocaleString('ko-KR', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' });
}
updateTime();
setInterval(updateTime, 60000);

// 사이드바 토글 (모바일)
function toggleSidebar() {
    const sidebar = document.getElementById('sidebar');
    const overlay = document.getElementById('sidebar-overlay');
    sidebar.classList.toggle('-translate-x-full');
    overlay.classList.toggle('hidden');
}

// 폼 제출 중복 방지
document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('form').forEach(form => {
        form.addEventListener('submit', (e) => {
            const btn = form.querySelector('button[type="submit"]');
            if (btn && !btn.disabled) {
                setTimeout(() => {
                    btn.disabled = true;
                    btn.textContent = '처리 중...';
                }, 0);
            }
        });
    });

    // 숫자 입력 필드 모바일 키패드
    document.querySelectorAll('input[type="number"]').forEach(input => {
        input.setAttribute('inputmode', 'numeric');
    });

    // 자동완성 엔터키 처리
    document.querySelectorAll('input[list]').forEach(input => {
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') e.preventDefault();
        });
    });
});

// 알림 자동 닫기
document.querySelectorAll('.alert-auto-close').forEach(el => {
    setTimeout(() => el.remove(), 4000);
});
