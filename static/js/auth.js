document.addEventListener('keydown', event => {
  if (event.key === 'Tab') document.body.classList.add('keyboard-navigation');
});
document.addEventListener('pointerdown', () => document.body.classList.remove('keyboard-navigation'));

document.querySelectorAll('.eye').forEach(button => {
  button.addEventListener('click', () => {
    const input = document.getElementById(button.dataset.target);
    const show = input.type === 'password';
    input.type = show ? 'text' : 'password';
    button.querySelector('i').className = show ? 'fas fa-eye-slash' : 'fas fa-eye';
    button.setAttribute('aria-pressed', String(show));
  });
});
