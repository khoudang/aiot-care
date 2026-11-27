/* Presets reuse the dashboard's correlated PWM command and telemetry path. */
function initFanLevels(isConnected = () => true) {
  const levels = [{label:'Tắt',value:0},{label:'Nhẹ',value:50},{label:'Vừa',value:75},{label:'Mạnh',value:100}];
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
      button.textContent = level.value === 0 ? level.label : level.label + ' ' + level.value + '%';
      button.setAttribute('aria-label', button.textContent);
      button.addEventListener('click', () => selectSpeed(level.value));
      group.append(button);
    }

    function sync() {
      const speed = Number(range.value);
      const disabled = range.disabled || !isConnected();
      Array.from(group.children).forEach((button, index) => {
        button.disabled = disabled;
        button.setAttribute('aria-pressed', String(speed === levels[index].value));
      });

    }
    new MutationObserver(sync).observe(range, {attributes:true, attributeFilter:['disabled']});
    const value = document.getElementById(prefix + '-val');
    if (value) new MutationObserver(sync).observe(value, {childList:true, characterData:true, subtree:true});
    range.addEventListener('input', sync);
    card.append(group);
    sync();
  }
}
