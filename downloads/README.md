# Портативная сборка Zapret-Zen 2.1e (Windows x64)

Файл: `Zapret-Zen-2.1e-portable-win64.zip` — 41 525 658 байт (~39,6 МБ)
SHA-256: `6e089ffbd8e353e8679e060242b287cc1d97567b38c976d895ea19f4535663f3`

## Как скачать

* Прямая ссылка (GitHub, ветка `arena/c452d19e-zapret-zen`):
  <https://github.com/MERAD-dsg/Zapret-Zen/raw/refs/heads/arena/c452d19e-zapret-zen/downloads/Zapret-Zen-2.1e-portable-win64.zip>
* Страница файла с кнопкой «Download raw file»:
  <https://github.com/MERAD-dsg/Zapret-Zen/blob/arena/c452d19e-zapret-zen/downloads/Zapret-Zen-2.1e-portable-win64.zip>

Архив лежит в git намеренно: `uploads.github.com` (загрузка ассетов в релизы)
в среде сборки заблокирован, поэтому релиз-ассет создать не удалось.
После публикации обычного релиза этот файл можно удалить из репозитория.

## Проверка после скачивания

Windows PowerShell:

```powershell
Get-FileHash .\Zapret-Zen-2.1e-portable-win64.zip -Algorithm SHA256
```

Ожидаемое значение — см. `Zapret-Zen-2.1e-portable-win64.zip.sha256` выше.

## Запуск

1. Распаковать архив целиком в папку с правами записи (не в `Program Files`,
   не запускать из ZIP).
2. `run_zapret_zen.cmd` → согласиться на запрос администратора (нужен WinDivert).
3. Если не стартует — `run_zapret_zen_console.cmd` покажет версии Python/PySide6
   и текст ошибки; логи лежат в `logs`.

Подробности — в `ПРОЧТИ_МЕНЯ.txt` внутри архива.

## Как пересобрать

```bash
python scripts/setup_portable_cache.py          # embeddable Python + колёса
python scripts/build_portable.py --zip dist/Zapret-Zen-2.1e-portable-win64.zip \
    --zip-prefix Zapret-Zen-2.1e-portable
```
