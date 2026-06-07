# Поиск клиентов

GUI поверх OpenStreetMap: ищет бизнес по городу/нишам, проверяет их сайты,
выдаёт CSV с «горячестью» лида (score).

## Готовый Windows .exe (для менеджера)

1. Открой вкладку **Actions** в этом репозитории на GitHub.
2. Возьми последний успешный запуск **Build Windows EXE** (зелёная галка).
3. Внизу, в разделе **Artifacts**, скачай **PoiskKlientov-windows** (zip).
4. Распакуй → внутри `PoiskKlientov.exe`.
5. Отдай менеджеру. Двойной клик — Python НЕ нужен.

Первый запуск: Windows SmartScreen может предупредить (неподписанный exe) →
«Подробнее» → «Выполнить в любом случае».

## Локально (Mac/Linux, для разработки)

    pip install -r requirements.txt
    python lead_finder_gui.py
