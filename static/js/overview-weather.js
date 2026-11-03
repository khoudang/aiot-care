/* Open-Meteo weather is independent of indoor telemetry and device controls. */
(() => {
  'use strict';
  const location = document.getElementById('weather-location');
  if (!location) return;
  const status = document.getElementById('weather-status');
  const dataBox = document.getElementById('weather-data');
  const forecast = document.getElementById('weather-forecast');
  const hourly = document.getElementById('weather-hourly');
  const expand = document.getElementById('weather-expand');
  const outlook = document.getElementById('weather-outlook');
  const mobile = window.matchMedia('(max-width:760px)');
  let expanded = false;
  function updateDisclosure() {
    outlook.hidden = mobile.matches && !expanded;
    expand.setAttribute('aria-expanded', String(!outlook.hidden));
    expand.querySelector('span').textContent = expanded ? 'Thu gọn dự báo' : 'Xem thêm dự báo';
  }
  expand.addEventListener('click', () => { expanded = !expanded; updateDisclosure(); });
  mobile.addEventListener('change', updateDisclosure);
  updateDisclosure();
  let mode = 'temperature', latest = null;
  const icon = code => code === 0 ? 'fa-sun' : code >= 95 ? 'fa-cloud-bolt' : code >= 71 && code <= 77 || code === 85 || code === 86 ? 'fa-snowflake' : code >= 51 && code <= 82 ? 'fa-cloud-rain' : 'fa-cloud';
  const element = (tag, className, text) => {
    const node = document.createElement(tag); node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  document.querySelectorAll('[data-weather-mode]').forEach(button => button.addEventListener('click', () => {
    mode = button.dataset.weatherMode;
    button.parentElement.style.setProperty('--weather-mode-index', ['temperature','rain','wind'].indexOf(mode));
    document.getElementById('weather-mode-title').textContent = {temperature:'Nhiệt độ',rain:'Lượng mưa',wind:'Gió'}[mode];
    document.querySelectorAll('[data-weather-mode]').forEach(b => b.setAttribute('aria-pressed', String(b === button)));
    if (latest) render(latest.data, latest.savedAt, latest.stale);
  }));
  let settings = null;
  const ttl = 15 * 60 * 1000;
  let controller;
  let generation = 0;
  function read(key) { try { return JSON.parse(localStorage.getItem(key)); } catch (_) { return null; } }
  function save(key, value) { try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) {} }
  function condition(code) {
    if (code === 0) return 'Trời quang';
    if ([1, 2, 3].includes(code)) return 'Có mây';
    if ([45, 48].includes(code)) return 'Sương mù';
    if ([51, 53, 55, 56, 57].includes(code)) return 'Mưa phùn';
    if ([61, 63, 65, 66, 67, 80, 81, 82].includes(code)) return 'Có mưa';
    if ([71, 73, 75, 77, 85, 86].includes(code)) return 'Có tuyết';
    if ([95, 96, 99].includes(code)) return 'Dông';
    return 'Chưa rõ trạng thái';
  }
  const number = value => typeof value === 'number' && Number.isFinite(value);
  function valid(data) {
    return data && data.current && number(data.current.temperature_2m) &&
      number(data.current.relative_humidity_2m) && data.daily &&
      ['time', 'weather_code', 'temperature_2m_max', 'temperature_2m_min', 'precipitation_probability_max']
        .every(key => Array.isArray(data.daily[key]) && data.daily[key].length >= 3);
  }
  function render(data, savedAt, stale = false) {
    latest = {data, savedAt, stale};
    const c = data.current;
    document.getElementById('weather-temperature').textContent = Math.round(c.temperature_2m);
    document.getElementById('weather-condition').textContent = condition(c.weather_code);
    document.getElementById('weather-humidity').textContent = Math.round(c.relative_humidity_2m) + '%';
    document.getElementById('weather-icon').className = 'fas ' + icon(c.weather_code);
    forecast.replaceChildren();
    const d = data.daily;
    const temperatures = [...d.temperature_2m_min.slice(0,3), ...d.temperature_2m_max.slice(0,3)].filter(number);
    const floor = Math.min(...temperatures) - 2, ceiling = Math.max(...temperatures) + 2;
    hourly.replaceChildren();
    const h = data.hourly;
    const now = Math.floor(Date.now()/3600000)*3600000;
    const offset = (data.utc_offset_seconds || 0)*1000;
    const start = h && Array.isArray(h.time) ? h.time.findIndex(t => Date.parse(t+'Z')-offset >= now) : -1;
    if(start >= 0) h.time.slice(start,start+12).forEach((time,j) => {
      const index = start+j, li = element('li','hourly-item');
      const code = h.weather_code?.[index];
      const symbol = element('i','fas '+(mode==='rain'?'fa-droplet':mode==='wind'?'fa-wind':icon(code)));
      symbol.setAttribute('aria-hidden','true');
      const value = mode==='rain' ? h.precipitation_probability?.[index] : mode==='wind' ? h.wind_speed_10m?.[index] : h.temperature_2m?.[index];
      const unit = mode==='rain'?'%':mode==='wind'?' km/h':'°';
      li.append(element('span','hourly-time',j===0?'Bây giờ':time.slice(11,13)+' giờ'),symbol,element('strong','hourly-value',number(value)?Math.round(value)+unit:'--'));
      if(mode==='rain')li.append(element('small','hourly-detail',number(h.precipitation?.[index])?h.precipitation[index]+' mm':'--'));
      if(mode==='wind')li.append(element('small','hourly-detail',number(h.wind_gusts_10m?.[index])?'Giật '+Math.round(h.wind_gusts_10m[index]):'--'));
      hourly.append(li);
    });
    else hourly.append(element('li','hourly-empty','Chưa có dự báo theo giờ.'));
    forecast.dataset.mode = mode;
    d.time.slice(0, 3).forEach((day, index) => {
      const li = element('li', 'forecast-row');
      const date = new Date(day + 'T12:00:00Z');
      const label = element('div', 'forecast-day');
      label.append(element('strong', '', index === 0 ? 'Hôm nay' : index === 1 ? 'Ngày mai' : new Intl.DateTimeFormat('vi-VN', {weekday:'long',timeZone:'UTC'}).format(date)),
        element('span', 'forecast-date', new Intl.DateTimeFormat('vi-VN', {day:'2-digit',month:'2-digit',timeZone:'UTC'}).format(date)),
        element('span', 'forecast-mobile-condition', condition(d.weather_code[index])));
      const symbol = element('i', 'fas ' + icon(d.weather_code[index])); symbol.setAttribute('aria-hidden','true');
      const low = d.temperature_2m_min[index], high = d.temperature_2m_max[index];
      const range = element('span', 'forecast-range'); range.setAttribute('aria-hidden','true');
      const fill = element('span', '');
      if(number(low) && number(high) && high >= low) {
        fill.style.left = ((low-floor)/(ceiling-floor)*100) + '%';
        fill.style.width = ((high-low)/(ceiling-floor)*100) + '%';
        range.append(fill);
      }
      const rain = d.precipitation_probability_max[index];
      const precipitation = element('div','forecast-rain');
      const rainBar = element('span','rain-track'); rainBar.setAttribute('aria-hidden','true');
      const rainFill = element('span','');
      if(number(rain)) { rainFill.style.width = Math.max(0,Math.min(100,rain)) + '%'; rainBar.append(rainFill); }
      precipitation.append(rainBar, element('strong','',number(rain) ? Math.round(rain)+'%' : '--'));
      precipitation.setAttribute('aria-label', 'Khả năng mưa ' + (number(rain) ? Math.round(rain)+'%' : '--'));
      li.append(label, symbol, element('span','forecast-condition',condition(d.weather_code[index])),
        element('span','forecast-low',number(low) ? Math.round(low)+'°' : '--'), range,
        element('strong','forecast-high',number(high) ? Math.round(high)+'°' : '--'), precipitation);
      if(mode !== 'temperature') {
        const value = mode==='rain' ? d.precipitation_sum?.[index] : d.wind_speed_10m_max?.[index];
        const unit = mode==='rain'?' mm':' km/h';
        const measure = element('strong','daily-measure',number(value)?Math.round(value*10)/10+unit:'--');
        const detail = mode==='rain' ? precipitation : element('span','daily-detail',number(d.wind_gusts_10m_max?.[index])?'Giật '+Math.round(d.wind_gusts_10m_max[index])+' km/h':'--');
        symbol.className = 'fas '+(mode==='rain'?'fa-droplet':'fa-wind');
        li.replaceChildren(label,symbol,measure,detail);
      }
      forecast.append(li);
    });
    dataBox.hidden = false;
    const time = new Intl.DateTimeFormat('vi-VN', { hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Ho_Chi_Minh' }).format(new Date(savedAt));
    status.textContent = stale ? `Chưa tải được dữ liệu mới. Đang hiển thị bản lưu lúc ${time}.` : '';
  }
  async function update() {
    const token = ++generation;
    if (controller) controller.abort();
    const city = settings && settings.city;
    if (!city || !number(settings.latitude) || !number(settings.longitude)) {
      dataBox.hidden = true;
      status.textContent = 'Quản trị viên có thể chọn địa điểm trong Cấu hình.';
      return;
    }
    const key = 'aiot-weather-v2-' + city;
    let cache = read(key);
    if (!cache || !valid(cache.data) || !number(cache.at)) cache = null;
    if (cache) render(cache.data, cache.at, Date.now() - cache.at >= ttl);
    else { dataBox.hidden = true; status.textContent = 'Đang tải dự báo…'; }
    if (cache && Date.now() - cache.at >= 0 && Date.now() - cache.at < ttl) return;
    controller = new AbortController();
    const requestController = controller;
    const timeout = setTimeout(() => requestController.abort(), 10000);
    try {
      const {latitude, longitude} = settings;
      const params = new URLSearchParams({ latitude, longitude, timezone: 'auto', forecast_days: 3,
        current: 'temperature_2m,relative_humidity_2m,weather_code',
        hourly: 'temperature_2m,weather_code,precipitation_probability,precipitation,wind_speed_10m,wind_gusts_10m',
        daily: 'weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,wind_speed_10m_max,wind_gusts_10m_max' });
      const response = await fetch('https://api.open-meteo.com/v1/forecast?' + params, { signal: requestController.signal });
      if (!response.ok) throw new Error('Weather service unavailable');
      const data = await response.json();
      if (!valid(data)) throw new Error('Invalid forecast');
      if (token !== generation) return;
      const at = Date.now();
      save(key, { data, at });
      render(data, at);
    } catch (_) {
      if (token !== generation) return;
      if (cache) render(cache.data, cache.at, true);
      else status.textContent = 'Chưa tải được thời tiết. Kiểm tra kết nối Internet; hệ thống sẽ tự thử lại.';
    } finally { clearTimeout(timeout); }
  }
  async function loadSettings() {
    const configController = new AbortController();
    const timer = setTimeout(() => configController.abort(), 10000);
    try {
      const response = await fetch('/api/weather-location', {cache:'no-store', signal:configController.signal});
      if (!response.ok) throw new Error('Cannot load location');
      settings = await response.json();
      location.textContent = settings.name || 'Chưa cấu hình địa điểm';
      update();
    } catch (_) {
      status.textContent = 'Chưa tải được cấu hình thời tiết. Hệ thống sẽ tự thử lại.';
    } finally { clearTimeout(timer); }
  }
  window.addEventListener('weather-location-changed', loadSettings);
  loadSettings();
  setInterval(() => { if (!document.hidden) loadSettings(); }, ttl);
})();
