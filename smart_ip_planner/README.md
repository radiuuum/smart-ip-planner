# Smart IP Planner

**Тема:** «Компьютерлік желідегі IP-адрестерді автоматты жоспарлау және бөлу құралын жасау»

Веб-приложение для автоматического планирования (VLSM/FLSM), диагностики (NET-001…NET-010), автоисправлений (Сценарии A и B) и моделирования роста IPv4-сетей, реализованное строго по ТЗ v1.0.

## Деплой на Streamlit Community Cloud (без нагрузки на MacBook)

1. Распакуйте архив и загрузите папку `smart_ip_planner` в репозиторий GitHub.
2. Откройте [share.streamlit.io](https://share.streamlit.io) → **Create app** → выберите репозиторий.
3. В поле **Main file path** укажите `app.py` (или `streamlit_app.py` — оба файла работают).
4. Нажмите **Deploy**.

## Локальный запуск (macOS / Windows / Linux)

```bash
cd smart_ip_planner
python3 -m venv .venv
source .venv/bin/activate       # macOS / Linux
# .venv\Scripts\activate        # Windows

pip install -r requirements.txt
streamlit run app.py
```

## Запуск 19 приёмочных тестов (раздел 8.1 ТЗ)

```bash
pytest -v
```
