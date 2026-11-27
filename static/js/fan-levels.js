/* Presets reuse the dashboard's correlated PWM command and telemetry path. */
function initFanLevels(isConnected = () => true) {
  const levels = [{label:'Nhẹ',value:50},{label:'Vừa',value:75},{label:'Mạnh',value:100}];
  for (const prefix of ['pt-fan', 'lv-fan', 'kt-exhaust']) {
    const range = document.getElementById(prefix + '-range');
    const card = range?.closest('.device-card-modern');
    if (!card) continue;
    const slider = card.querySelector('.device-slider-control') || card.querySelector('.ha-range-control');
    if (slider) slider.hidden = true;
    const power = card.querySelector('.sw');
    if (power) power.hidden = true;
    const group = document.createElement('div');
    group.className = 'fan-levels';
    group.setAttribute('role', 'group');
    group.setAttribute('aria-label', 'Mức tốc độ quạt');
    function selectSpeed(value) {
      if (range.disabled || !isConnected()) return;
      range.value = value;
      range.dispatchEvent(new Event('input', {bubbles:true}));
      range.dispatchEvent(new Event('change', {bubbles:true}));
    }
    for (const level of levels) {
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = level.label + ' ' + level.value + '%';
      button.setAttribute('aria-label', button.textContent);
      button.addEventListener('click', () => selectSpeed(level.value));
      group.append(button);
    }
    const steps = document.createElement('div');
    steps.className = 'fan-step-controls';
    const minus = document.createElement('button'), plus = document.createElement('button');
    minus.type = plus.type = 'button';
    minus.textContent = '−'; plus.textContent = '+';
    minus.setAttribute('aria-label', 'Giảm tốc độ quạt; mức cuối là tắt');
    plus.setAttribute('aria-label', 'Tăng tốc độ quạt');
    minus.addEventListener('click', () => selectSpeed([100,75,50,0].find(value => value < Number(range.value)) ?? 0));
    plus.addEventListener('click', () => selectSpeed([0,50,75,100].find(value => value > Number(range.value)) ?? 100));
    function sync() {
      const speed = Number(range.value);
      const disabled = range.disabled || !isConnected();
      Array.from(group.children).forEach((button, index) => {
        button.disabled = disabled;
        button.setAttribute('aria-pressed', String(speed === levels[index].value));
      });
      minus.disabled = disabled || speed <= 0;
      plus.disabled = disabled || speed >= 100;
    }
    new MutationObserver(sync).observe(range, {attributes:true, attributeFilter:['disabled']});
    const value = document.getElementById(prefix + '-val');
    if (value) new MutationObserver(sync).observe(value, {childList:true, characterData:true, subtree:true});
    range.addEventListener('input', sync);
    steps.append(minus, plus);
    card.append(group, steps);
    sync();
  }
}
