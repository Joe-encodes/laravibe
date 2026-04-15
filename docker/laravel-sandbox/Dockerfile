FROM php:8.3-cli-alpine

LABEL maintainer="Adamu Joseph Obinna"
LABEL description="Laravel 12 AI Repair Sandbox — PHP 8.3 + Boost + Pest"

# ── 1. Mirror Optimization ───────────────────────────────────────────────────
# Use the global CDN to prevent hangs during package downloads
RUN sed -i 's/dl-cdn.alpinelinux.org/uk.alpinelinux.org/g' /etc/apk/repositories || true

# ── 2. System dependencies (Base) ──────────────────────────────────────────
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
    oniguruma

# ── 3. Build dependencies (Temporary) ──────────────────────────────────────
# Compiled with parallel jobs to maximize CPU usage and prevent timeouts
RUN apk add --no-cache --virtual .build-deps \
    $PHPIZE_DEPS \
    icu-dev \
    libzip-dev \
    libpng-dev \
    libjpeg-turbo-dev \
    libwebp-dev \
    oniguruma-dev \
    && docker-php-ext-configure gd --with-jpeg --with-webp \
    && docker-php-ext-install -j$(nproc) \
        pdo \
        pdo_mysql \
        gd \
        bcmath \
        intl \
        mbstring \
        zip \
        pcntl \
    && apk del .build-deps

# ── 4. Node.js & Tooling ────────────────────────────────────────────────────
RUN apk add --no-cache nodejs npm mysql-client

# ── 5. Redis + pcov PHP extensions ──────────────────────────────────────────
RUN apk add --no-cache --virtual .build-deps $PHPIZE_DEPS \
    && MAKEFLAGS="-j$(nproc)" pecl install redis pcov \
    && docker-php-ext-enable redis pcov \
    && apk del .build-deps

# ── 6. Composer ─────────────────────────────────────────────────────────────
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
ENV COMPOSER_ALLOW_SUPERUSER=1
ENV COMPOSER_NO_INTERACTION=1

WORKDIR /var/www

# ── 7. Create Laravel 12 project ─────────────────────────────────────────────
RUN composer create-project laravel/laravel sandbox "12.*" --prefer-dist --no-progress

WORKDIR /var/www/sandbox

# ── 8. Install Laravel packages ──────────────────────────────────────────────
RUN composer require laravel/sanctum predis/predis --no-progress && \
    composer require --dev \
        laravel/boost \
        "pestphp/pest:^3.0" \
        "pestphp/pest-plugin-laravel:^3.0" \
        "pestphp/pest-plugin-mutate:^3.0" \
        --with-all-dependencies \
        --no-progress

# ── 9. Initialise Pest ───────────────────────────────────────────────────────
RUN ./vendor/bin/pest --init

# ── 10. Permissions & Setup ──────────────────────────────────────────────────
RUN addgroup -S sandbox && adduser -S -G sandbox sandbox \
    && chown -R sandbox:sandbox /var/www/sandbox \
    && chmod -R 755 /var/www/sandbox/storage

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh \
    && php artisan vendor:publish --tag=boost-config --force 2>/dev/null || true \
    && php artisan boost:install --skill=rest-api --skill=pest-api --force 2>/dev/null || true \
    && php artisan optimize 2>/dev/null || true


ENTRYPOINT ["/entrypoint.sh"]
