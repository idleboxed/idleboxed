# idleboxed

Сборщик комплектов Idle для RK3032 и Linux x86-64.
Python-пакет и команда — **iboxed**. Публикация — в GitHub Releases через `gh`.

## Подготовка

Нужны Linux x86-64, Python 3.12+, `uv`, Git, GitHub CLI и инструменты сборки
[iroll](https://github.com/idleboxed/iroll/blob/main/docs/rollout.md).
Для RK3032 заранее подготовьте [SDK](https://github.com/idleboxed/iroll/blob/main/docs/sdk.md)
в `in/sdk/rk3032`.

```bash
git clone --recurse-submodules https://github.com/idleboxed/idleboxed.git
cd idleboxed
uv tool install --force -e .
iboxed --help
```

Для уже клонированного репозитория: `git submodule update --init`.

## Сборка

Отредактируйте [config.toml](config.toml), зафиксируйте изменения в Git и запускайте
команду из каталога интеграционного репозитория:

```bash
iboxed build
```

`version` — номер всего комплекта; `[[platforms]]` — матрица сборки.
По умолчанию: RK3032 `standard`/`diag` и Linux x86-64 `standard`.
`standard` — без пассивной диагностики iman, `diag` — с ней.

### Закреплённый состав и свежие ветки

Обычная сборка использует закреплённые коммиты компонентов.
Для сборки с текущих веток `main`:

```bash
iboxed build --latest
```

### Результат

Готовый комплект — в `out/<version>/`. При повторной сборке каталог этой версии
очищается автоматически. Для стандартной матрицы:

```text
iboxed-0.1.0-rk3032-standard.tar.gz
iboxed-0.1.0-rk3032-diag.tar.gz
iboxed-0.1.0-linux-x86_64-standard.tar.gz
release.json
```

В архивах — приложения в `system/`, инструкция и пустые каталоги сохранений.
Сведения о выпуске и лицензиях — `system/release.json` и `system/THIRD_PARTY.txt`.
Внешний `release.json` нужен для публикации. ROM и BIOS не входят.

Трамплин устанавливается отдельно через
[itrampoline](https://github.com/idleboxed/itrampoline/blob/main/docs/usage.md).
Распаковывайте комплект на SD после остановки приложений; после записи размонтируйте карту.

## Публикация

Авторизуйтесь в `gh` с правом создания Releases и запускайте отдельно:

```bash
iboxed publish
```

Для каждого нового выпуска выбирайте новую `version`: опубликованные выпуски
не заменяются. Сборка с `--latest` публикуется как prerelease.
При ошибке загрузки осмотрите оставшийся draft перед повторной публикацией.

## Разработка и лицензия

[Проверки и структура пакета](docs/development.md), [IDLE.md](IDLE.md).
Собственный код — [BSD-3-Clause](LICENSE); сторонние компоненты сохраняют свои лицензии.
