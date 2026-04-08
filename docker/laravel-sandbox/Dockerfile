FROM php:8.3-cli-alpine

LABEL maintainer="Adamu Joseph Obinna"
LABEL description="Laravel 12 AI Repair Sandbox — PHP 8.3 + Boost + Pest"

# ── System dependencies ──────────────────────────────────────────────────────
RUN apk add --no-cache \
    bash \
    curl \
    git \
    unzip \
    nodejs \
    npm \
    mysql-client \
    libpng-dev \
    libjpeg-turbo-dev \
    libwebp-dev \
    icu-dev \
    oniguruma-dev \
    libzip-dev \
    && docker-php-ext-configure gd --with-jpeg --with-webp \
    && docker-php-ext-install \
        pdo \
        pdo_mysql \
        gd \
        bcmath \
        intl \
        mbstring \
        zip \
        pcntl

# ── Redis + pcov PHP extensions ─────────────────────────────────────────────
# pcov is the lightweight coverage driver required by pest --mutate.
# Installing both in the same layer keeps PHPIZE_DEPS build deps to one RUN step.
RUN apk add --no-cache --virtual .build-deps $PHPIZE_DEPS \
    && pecl install redis pcov \
    && docker-php-ext-enable redis pcov \
    && apk del .build-deps

# ── Composer ────────────────────────────────────────────────────────────────
COPY --from=composer:2 /usr/bin/composer /usr/bin/composer
ENV COMPOSER_ALLOW_SUPERUSER=1
ENV COMPOSER_NO_INTERACTION=1

# ── Create Laravel 12 project ────────────────────────────────────────────────
# Layer this separately so composer install is cached when only code changes
WORKDIR /var/www

RUN composer create-project laravel/laravel sandbox "12.*" --prefer-dist --no-progress

WORKDIR /var/www/sandbox

# ── Install Laravel packages (cached layer) ──────────────────────────────────
RUN composer require laravel/sanctum --no-progress && \
    composer require predis/predis --no-progress

RUN composer require --dev \
        laravel/boost \
        "pestphp/pest:^3.0" \
        "pestphp/pest-plugin-laravel:^3.0" \
        "pestphp/pest-plugin-mutate:^3.0" \
        --with-all-dependencies \
        --no-progress

# ── Initialise Pest ──────────────────────────────────────────────────────────
RUN ./vendor/bin/pest --init

# ── Laravel Boost installed via composer above (boost:install runs in entrypoint) ──

# ── Permissions ──────────────────────────────────────────────────────────────
RUN addgroup -S sandbox && adduser -S -G sandbox sandbox \
    && chown -R sandbox:sandbox /var/www/sandbox \
    && chmod -R 755 /var/www/sandbox/storage

# ── Copy startup script ──────────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# NOTE: Container runs entrypoint as root for artisan setup.
# User code execution uses --user sandbox via docker exec (see docker_service.py).

WORKDIR /var/www/sandbox

# ── Publish Boost config without interactive prompts ─────────────────────────
# boost:install uses laravel/prompts internally and ignores --no-interaction.
# Boost is already installed via composer require above; this just configures it.
RUN php artisan vendor:publish --tag=boost-config --force 2>/dev/null || true && \
    php artisan optimize 2>/dev/null || true

ENTRYPOINT ["/entrypoint.sh"]
