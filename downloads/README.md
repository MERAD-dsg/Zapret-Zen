# Zapret-Zen 2.1f — установщик и портативная сборка (Windows x64)

Два файла, оба уже содержат все исправления 2.1f:

| Файл | Размер | SHA-256 |
| --- | --- | --- |
| `Zapret-Zen-2.1f-setup.exe` — установщик «в один клик» (внутри уже лежит архив) | 42 162 688 байт (~40,2 МБ) | `c0801820a125b07b37e89b249b1aea71a80b857cb9cdf242455b61acf8745114` |
| `Zapret-Zen-2.1f-portable.zip` — портативная папка целиком | 41 694 695 байт (~39,8 МБ) | `a6e9035bd601db2f154d5eab55372327e2e2d06d3f7fce43b7852d7f41aee674` |

## Скачать

Прямые ссылки (ветка `arena/c452d19e-zapret-zen`):

* установщик:
  <https://github.com/MERAD-dsg/Zapret-Zen/raw/refs/heads/arena/c452d19e-zapret-zen/downloads/Zapret-Zen-2.1f-setup.exe>
* портативный архив:
  <https://github.com/MERAD-dsg/Zapret-Zen/raw/refs/heads/arena/c452d19e-zapret-zen/downloads/Zapret-Zen-2.1f-portable.zip>

Страницы файлов (кнопка «Download raw file»), если прямая ссылка не открывается:

* <https://github.com/MERAD-dsg/Zapret-Zen/blob/arena/c452d19e-zapret-zen/downloads/Zapret-Zen-2.1f-setup.exe>
* <https://github.com/MERAD-dsg/Zapret-Zen/blob/arena/c452d19e-zapret-zen/downloads/Zapret-Zen-2.1f-portable.zip>

Архив и установщик лежат в git намеренно: `uploads.github.com` (загрузка
ассетов в релизы) в среде сборки заблокирован, релиз-ассет создать не удалось.

## Что исправлено в 2.1f

1. **Больше нет «окна Python».** В архиве появился `Zapret-Zen.exe` — настоящий
   Windows-лаунчер (GUI-подсистема, своя иконка, версия, издатель). Он запускает
   `pythonw.exe` скрытно и сразу выходит; портативный `run_zapret_zen.cmd` тоже
   переведён с `python.exe` на `pythonw.exe`, поэтому чёрное консольное окно рядом
   с основным больше не висит. Запрос администратора (WinDivert) поднимает само
   приложение, причём повторный запуск идёт через `pythonw.exe`, а не `python.exe`.
2. **Убрано всплывающее «Компонент не запустился — winws exited; restarting in 15s».**
   Одиночный автоперезапуск winws больше не показывает системное уведомление —
   только статус в окне. Если winws не принимает параметры стратегии (кривой
   флаг, отсутствующий payload), супервизор больше не крутит вечный цикл
   «restarting in 15s», а останавливается и пишет причину: код выхода
   (0xC0000135 — нет DLL, 0xC0000005 — конфликт WinDivert/антивируса, 5 — нет
   прав) плюс подсказку, что делать.
3. **QUIC-блокировка включена по умолчанию.** Это ваш вывод: с ней winws падает
   заметно реже. Блокируется UDP/443 правилом брандмауэра (стратегии
   general*.bat не переписываются), YouTube идёт по TCP+TLS. При этом
   приложение не блокирует QUIC, если выбранная стратегия и так обходит весь
   UDP/443 — чтобы не ломать голос в Discord и игры.
4. **Discord Rich Presence выключен по умолчанию** (включается галочкой
   «Discord Rich Presence» в настройках).

## Установка (setup.exe)

1. Запустить `Zapret-Zen-2.1f-setup.exe`. Если Windows покажет «SmartScreen» —
   «Подробнее» → «Выполнить в любом случае» (файл не подписан).
2. Установка идёт в `%ProgramFiles%\Zapret-Zen`, создаётся ярлык в меню «Пуск»
   и запись «Программы и компоненты» → «Удалить».
3. Галочка «Запустить Zapret-Zen после установки» — по желанию.
4. Тихая установка: `Zapret-Zen-2.1f-setup.exe /S`.
5. Удаление: «Программы и компоненты» → Zapret-Zen → Удалить (или
   `"%ProgramFiles%\Zapret-Zen\Zapret-Zen.exe" --uninstall`). Удаляются ярлык,
   запись в реестре, правило брандмауэра для QUIC и папка программы; настройки
   пользователя в `%APPDATA%` сохраняются.

## Портативный запуск (zip)

1. Распаковать архив целиком (не запускать из ZIP) в папку с правами записи.
2. `Zapret-Zen.exe` — обычный запуск (рекомендуется).
   `run_zapret_zen.cmd` — то же самое через `pythonw.exe`;
   `run_zapret_zen_console.cmd` — диагностический запуск с консолью.
3. Согласиться на запрос администратора (нужен WinDivert).

## Проверка целостности

```powershell
Get-FileHash .\Zapret-Zen-2.1f-setup.exe -Algorithm SHA256
Get-FileHash .\Zapret-Zen-2.1f-portable.zip -Algorithm SHA256
```

Значения должны совпасть с таблицей выше (они же лежат в `*.sha256`).

## Как пересобрать

```bash
python scripts/setup_portable_cache.py                 # embeddable Python + колёса
pip install ziglang                                    # кросс-компилятор для .exe
python scripts/build_installer.py --prepare            # native/launcher/Zapret-Zen.exe
python scripts/build_portable.py --zip dist/Zapret-Zen-2.1f-portable.zip \
    --zip-prefix Zapret-Zen-2.1f-portable
python scripts/build_installer.py --payload dist/Zapret-Zen-2.1f-portable.zip \
    --out dist_native                                  # Zapret-Zen-2.1f-setup.exe
```
