# BuildVision — мобильное приложение (Capacitor)

Обёртка веб-кода в нативный Android-проект через [Capacitor](https://capacitorjs.com/) —
без переписывания на React Native/Flutter. Переиспользует тот же backend API,
что и веб-фронтенд (`frontend/`), ту же сессионную авторизацию и тёмную тему
BuildVision (`src/styles/tokens.css` — копия `frontend/src/styles/tokens.css`).

## Экраны

Нижняя навигация (5 вкладок) + экран входа:

1. **Вход** (`/login`) — тот же `POST /api/auth/login`, что и в вебе.
2. **Главная** (`/`) — упрощённая сводка: счётчики зон/камер/отклонений, банер риска, список зон.
3. **Карта** (`/map`) — Leaflet-карта площадки с зонами (тот же `/api/site`, что и в вебе).
4. **Анализ** (`/analysis`) — снимок с камеры телефона (`@capacitor/camera`) → `POST /api/observations`,
   тот же сквозной сценарий анализа, что и на веб-экране «Камера — AI-анализ».
   Нативную камеру нужно отдельно проверить на Android-устройстве.
5. **Уведомления** (`/notifications`) — список последних отклонений (`/api/notifications`).
6. **Профиль** (`/profile`) — реальный вошедший пользователь (ФИО, должность, роль) + выход.

Push-уведомления не реализованы в этом цикле (см. план) — список уведомлений тянется при
открытии вкладки.

## Разработка

```powershell
npm install
cp .env.example .env   # или создать .env вручную, см. ниже
npm run dev
```

`.env`:

```
VITE_API_BASE_URL=https://your-domain.example
```

Для локальной отладки на устройстве/эмуляторе укажите доступный с телефона адрес backend
(не `localhost` — с точки зрения эмулятора/устройства это будет не та машина).

## Сборка и синхронизация с Android-проектом

```powershell
npm run build        # собирает dist/ (tsc -b && vite build)
npx cap sync android # копирует dist/ в android/app/src/main/assets/public
# или одной командой:
npm run cap:sync
```

Каталог `android/` уже создан в этом репозитории (`npx cap add android`) и синхронизирован —
это полноценный проект Android Studio/Gradle с подключённым плагином `@capacitor/camera`.

## Сборка Android

Настроена подписанная **release-сборка APK** для RuStore: пакет `ru.buildvision.app`,
версия `1.0.0`, `versionCode = 2`, Android 6.0+ (`minSdk 23`, `targetSdk 35`).
Debug-сборка остаётся только для разработки, не для распространения пользователям.

**Важное уточнение по версии JDK:** несмотря на то, что многие руководства по Capacitor
упоминают JDK 17, `@capacitor/android@7.4.4` требует именно **JDK 21** — с JDK 17 сборка падает
с ошибкой `error: invalid source release: 21` на шаге `:capacitor-android:compileDebugJavaWithJavac`.

### Локальная установка без Android Studio (проверено на Windows)

Чтобы не занимать место на системном диске (см. аналогичное ограничение в корневом README
про кэши torch/npm), всё ставится в отдельный каталог вне `C:`:

```powershell
# JDK 21 (Eclipse Temurin, портативный zip)
Invoke-WebRequest "https://api.adoptium.net/v3/binary/latest/21/ga/windows/x64/jdk/hotspot/normal/eclipse?project=jdk" -OutFile jdk21.zip
Expand-Archive jdk21.zip -DestinationPath D:\dev\android-tools\jdk21-extract
# переименовать распакованную папку в D:\dev\android-tools\jdk-21

# Android SDK command-line tools
Invoke-WebRequest "https://dl.google.com/android/repository/commandlinetools-win-13114758_latest.zip" -OutFile cmdline-tools.zip
# распаковать в D:\dev\android-tools\sdk\cmdline-tools\latest (см. структуру ниже)
```

Структура каталогов должна быть точно такой: `sdk/cmdline-tools/latest/bin/sdkmanager.bat`.
Затем установить пакеты и принять лицензии (`platforms;android-35`/`build-tools;35.0.0` берутся из
`android/variables.gradle`; `build-tools;34.0.0` дотянется автоматически как транзитивная зависимость Capacitor):

```powershell
$env:JAVA_HOME = "D:\dev\android-tools\jdk-21"
1..15 | ForEach-Object { "y" } | & "D:\dev\android-tools\sdk\cmdline-tools\latest\bin\sdkmanager.bat" `
  --sdk_root=D:\dev\android-tools\sdk "platform-tools" "platforms;android-35" "build-tools;35.0.0"
```

Создать `android/local.properties` (не коммитится, уже в `.gitignore`):

```
sdk.dir=D\:\\dev\\android-tools\\sdk
```

Для локальной debug-сборки:

```powershell
npm run build; npx cap sync android
cd android
$env:JAVA_HOME = "D:\dev\android-tools\jdk-21"
$env:ANDROID_HOME = "D:\dev\android-tools\sdk"
$env:GRADLE_USER_HOME = "D:\dev\caches\gradle"   # чтобы кэш Gradle тоже не занимал системный диск
.\gradlew.bat assembleDebug --no-daemon
```

Результат: `android/app/build/outputs/apk/debug/app-debug.apk`. Сам файл APK в git не коммитится
(см. `.gitignore`, `mobile/android/app/build/`) — собирается заново из исходников по этим шагам.

### Вариант — Android Studio

```powershell
npm run cap:open   # откроет android/ в Android Studio
```

Для релиза предпочтителен сценарий ниже: он дополнительно проверяет сертификат и пакет.

### Подписанный release APK

Из каталога `mobile/` в PowerShell:

```powershell
$env:JAVA_HOME = "D:\dev\android-tools\jdk-21"
$env:ANDROID_HOME = "D:\dev\android-tools\sdk"
$env:GRADLE_USER_HOME = "D:\dev\caches\gradle"
.\scripts\build-release.ps1 -ApiBaseUrl https://your-domain.example
```

Сценарий запускает mobile lint, TypeScript/Vite build, Capacitor sync,
`lintRelease`/`assembleRelease`, `apksigner` и `zipalign`. Адрес API задаётся обязательным
параметром `-ApiBaseUrl` (или переменной окружения `VITE_API_BASE_URL`), например
`.\scripts\build-release.ps1 -ApiBaseUrl https://your-domain.example`. Проверяются идентификатор, SDK,
отключённая отладка и совпадение отпечатка сертификата с приватной конфигурацией.
Подпись не подменяется debug-ключом.

Результаты в `release/` (не входят в Git):

* `BuildVision-1.0.0-2.apk` — подписанный установочный файл для пользователей/RuStore.
* `rustore-icon-512.png` — иконка карточки, 512×512, непрозрачный фон.
* `SHA256SUMS.txt`, `release-info.json` — контрольная сумма и параметры APK.
* `release-certificate.pem` — публичный сертификат, не закрытый ключ.

Для следующей публикации увеличьте `versionCode` в `android/app/build.gradle`;
поддерживайте согласованность `versionName`, `package.json` и `package-lock.json`.
AAB и загрузка закрытого ключа в консоль не нужны для выбранного сценария публикации APK.

### Сохранность ключа

**Ключ уже создан — не генерируйте другой для обновлений этого приложения.**
На этой машине приватные материалы находятся вне репозитория:

* `%USERPROFILE%\BuildVision-signing\buildvision-release.keystore` — RSA 4096, PKCS12.
* `%USERPROFILE%\BuildVision-signing\signing.json` — конфигурация сборки с секретами.
* `%USERPROFILE%\BuildVision-signing\Signing-access.txt` — сведения для восстановления.

Доступ к каталогу разрешён только владельцу. Сохраните весь каталог в отдельной
зашифрованной резервной копии; не загружайте его в RuStore, Git, переписку или общий диск.
Потеря ключа либо паролей может лишить возможности выпускать совместимые обновления.
После переноса на другую машину исправьте `storeFile` в приватной конфигурации,
сохраните ограниченные права доступа и передайте её путь через `-SigningConfig`.

Gradle получает `BUILDVISION_STORE_FILE`, `BUILDVISION_STORE_TYPE`,
`BUILDVISION_STORE_PASSWORD`, `BUILDVISION_KEY_ALIAS`, `BUILDVISION_KEY_PASSWORD`
только из окружения процесса. Сценарий заполняет их сам и восстанавливает окружение после
сборки. Не передавайте пароли в командной строке или `VITE_*`, не добавляйте их в исходники.
Без конфигурации подписи release-сборка намеренно завершается ошибкой.

**Старый debug APK нельзя обновить этим release APK поверх установки:** подписи разные.
На тестовом телефоне потребуется удалить debug-приложение (локальные данные будут удалены),
затем установить release. Если этот пакет уже опубликован с другим сертификатом, для
совместимого обновления нужен прежний ключ — новый не заменяет его.

## Фирменный логотип

Исходник: `resources/logo-source.png`. Генератор `scripts/generate_branding.py` использует
Python/Pillow и создаёт полный логотип входа, обычные/круглые/адаптивные/монохромные иконки,
заставку с сохранением пропорций и иконку RuStore. Точечное удаление прежних шаблонных
drawable входит в генерацию; остальные ресурсы не затрагиваются.

```powershell
# Из mobile/, Python должен иметь Pillow:
python .\scripts\generate_branding.py
.\scripts\build-release.ps1 -ApiBaseUrl https://your-domain.example
```

На Android 12+ используется системная заставка со знаком приложения;
на более ранних версиях — центрированный полный логотип. WebView debugging,
логи Capacitor и открытый HTTP отключены. Резервное копирование и перенос приватных
данных приложения запрещены настройками манифеста и правилами Android 12+.

## Авторизация и проверка cookie

Backend использует сессионный cookie Django (`sessionid`, см. `backend/app/auth.py`) — тот же
механизм, что и в вебе (`credentials: "include"`). Мобильное приложение грузится с `https://localhost`
(Capacitor Android, см. `capacitor.config.ts`), а API работает на вашем развёрнутом домене (`VITE_API_BASE_URL`).
Для этих cross-site запросов сервер ставит `SameSite=None; Secure; HttpOnly`, когда
`SK_SESSION_COOKIE_SECURE=true`. Capacitor разрешает third-party cookie своему WebView.
Каждый изменяющий запрос отправляет `X-BuildVision-Request: 1`; сервер дополнительно
проверяет разрешённый Origin. Пароли не входят в исходники или APK.

Проверено в Chrome с настоящими мобильными assets, origin `https://localhost` и действующим
API: вход обеими ролями, отклонение неверного/старого публичного пароля, CORS, сохранение сессии
после обновления страницы, выход и ограничение административных действий для участника.
Сетевые ошибки показываются отдельно от сообщения о неверном пароле.

**Проверка мобильного web-клиента не заменяет запуск APK на Android:** подключённого
устройства и установленного эмулятора во время проверки не было. Перед публикацией
проверьте release APK на телефоне: установку, иконку/заставку, вход обеими ролями,
сохранение сессии после перезапуска, выход, разрешения и работу камеры, сетевые ошибки.

## Материалы для RuStore Console

Подготовлены подписанный APK и фирменная иконка 512×512. Владелец аккаунта должен
дополнительно подготовить:

* Не менее 3 скриншотов с эмулятора/устройства.
* Короткое и полное описание на русском, категория, контакт разработчика.
* Сведения об обработке данных и политику конфиденциальности, соответствующие работе сервиса.
* Отдельный тестовый доступ для модераторов в закрытых полях консоли, не в публичном описании.
  Не используйте основной административный аккаунт в качестве публичного демо-доступа.

Регистрация, загрузка APK и отправка на модерацию — отдельный шаг владельца аккаунта.
Сборка файла не означает публикацию и не гарантирует прохождение модерации.
См. [требования к публикации](https://www.rustore.ru/help/developers/publishing-and-verifying-apps/app-publication)
и [подпись APK](https://www.rustore.ru/help/guides/sign-apk).
