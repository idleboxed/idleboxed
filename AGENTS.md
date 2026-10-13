# Инструкции агента

Следуй [IDLE.md](IDLE.md); явные уточнения этого проекта имеют приоритет.

`idleboxed` — интеграционный репозиторий; Python-пакет и команда — `iboxed`.
Сабмодули — в `components/`, состав сборки — в `config.toml`, код — в `src/iboxed/`,
тесты — в `tests/`. Рецепты компонентов принадлежат iroll.

Согласованный CLI: `iboxed build [--latest]`, `iboxed publish`.
Новые команды и параметры сначала согласовать с владельцем.

Уточнения к IDLE.md: установка — `uv tool install --force -e .`;
проверки — `ma tools`, `ma tests`, только Python 3.12; sdist включает тесты.
Использование и соглашения о выпусках — в [README.md](README.md),
разработка — в [docs/development.md](docs/development.md).
