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


// Existing cached login pages must expose only administrator-issued accounts.
document.querySelectorAll('a[href="/register"]').forEach(link=>{
  const container=link.closest('.bottom');
  if(container)container.remove();
  else link.remove();
});
if(location.pathname==='/register')location.replace('/login');
