FROM php:8.3-cli-alpine

LABEL maintainer="Adamu Joseph Obinna"
LABEL description="Laravel 12 AI Repair Sandbox — PHP 8.3 + Boost + Pest (SQLite)"

# ── 1. Mirror Optimization ────────────────────────────────────────────────────
RUN sed -i 's/dl-cdn.alpinelinux.org/uk.alpinelinux.org/g' /etc/apk/repositories || true

# ── 2. System dependencies ────────────────────────────────────────────────────
RUN apk add --no-cache \
    bash \
    curl \
    git \
    unzip \
    icu-libs \
    libzip \
    libpng \
    libjpeg-turbo \
    libwebp \
    oniguruma \
    sqlite \
    coreutils

# ── 3. Build dependencies + PHP extensions ────────────────────────────────────
# SQLite only — no pdo_mysql, no mysql-client needed
RUN apk add --no-cache --virtual .build-deps \
    $PHPIZE_DEPS \
    icu-dev \
    libzip-dev \
    libpng-dev \
    libjpeg-turbo-dev \
    libwebp-dev \
    oniguruma-dev \
    sqlite-dev \
    && docker-php-ext-configure gd --with-jpeg --with-webp \
    && docker-php-ext-install -j$(nproc) \
        pdo \
        pdo_sqlite \
        gd \
        bcmath \
        intl \
        mbstring \
        zip \
        pcntl \
    && apk del .build-deps

# ── 4. Redis + pcov PHP extensions ───────────────────────────────────────────
# redis — Laravel cache layer config compatibility
# pcov  — Pest mutation coverage (pest-plugin-mutate checks pcov.enabled at runtime)
RUN apk add --no-cache --virtual .build-deps $PHPIZE_DEPS \
    && MAKEFLAGS="-j$(nproc)" pecl install redis pcov \
    && docker-php-ext-enable redis pcov \
    && apk del .build-deps

# ── 4b. Activate pcov for mutation testing ────────────────────────────────────
# pest --mutate requires pcov.enabled=1 — installing the extension is not enough.
# Without this, every mutation run fails with "Extension pcov not found" regardless
# of whether pcov.so is loaded, making the mutation gate permanently soft-pass.
RUN echo "pcov.enabled=1" >> /usr/local/etc/php/conf.d/docker-php-ext-pcov.ini

# ── 5. Composer ───────────────────────────────────────────────────────────────
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
ENV COMPOSER_ALLOW_SUPERUSER=1
ENV COMPOSER_NO_INTERACTION=1

WORKDIR /var/www

# ── 6. Create Laravel 12 project ─────────────────────────────────────────────
RUN composer create-project laravel/laravel sandbox "12.*" --prefer-dist --no-progress

WORKDIR /var/www/sandbox

# ── 7. Install Laravel packages ───────────────────────────────────────────────
RUN composer require predis/predis --no-progress && \
    composer require --dev \
        laravel/boost \
        "pestphp/pest:^3.0" \
        "pestphp/pest-plugin-laravel:^3.0" \
        "pestphp/pest-plugin-mutate:^3.0" \
        --with-all-dependencies \
        --no-progress

# ── 8. Initialise Pest ────────────────────────────────────────────────────────
RUN ./vendor/bin/pest --init

# ── 9. Setup API and Install Boost ──────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && php artisan install:api --force \
    && php artisan vendor:publish --tag=boost-config --force 2>/dev/null || true \
    && php artisan boost:install --skill=rest-api --skill=pest-api --force 2>/dev/null || true

# ── 10. Permissions & Optimization ────────────────────────────────────────────
RUN addgroup -S sandbox && adduser -S -G sandbox sandbox \
    && chown -R sandbox:sandbox /var/www/sandbox \
    && chmod -R 777 /var/www/sandbox/storage \
    && php artisan optimize 2>/dev/null || true

ENTRYPOINT ["/entrypoint.sh"]
