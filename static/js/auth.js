document.querySelectorAll('.eye').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.target);
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.querySelector('i').className = show ? 'fas fa-eye-slash' : 'fas fa-eye';
    button.setAttribute('aria-pressed', String(show));
  });
});
