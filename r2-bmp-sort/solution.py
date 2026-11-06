#!/usr/bin/env python3
import sys
import os
import struct
import time
import statistics
import argparse


class BMPError(Exception):
    pass

def read_bmp(path):
    with open(path, "rb") as f:
        data = f.read()

    if len(data) < 54:
        raise BMPError("Файл слишком мал для BMP (меньше 54 байт)")

    if data[0:2] != b'BM':
        raise BMPError("Неверная сигнатура BMP (ожидается 'BM')")

    bfOffBits = struct.unpack_from("<I", data, 10)[0]
    biSize = struct.unpack_from("<I", data, 14)[0]
    biWidth = struct.unpack_from("<i", data, 18)[0]
    biHeight = struct.unpack_from("<i", data, 22)[0]
    biBitCount = struct.unpack_from("<H", data, 28)[0]
    biCompression = struct.unpack_from("<I", data, 30)[0]

    if biBitCount != 24:
        raise BMPError(f"Неподдерживаемая битность: {biBitCount} (ожидается 24)")
    if biCompression != 0:
        raise BMPError(f"Сжатые BMP не поддерживаются (compression={biCompression})")
    if biWidth <= 0 or biHeight == 0:
        raise BMPError("Некорректные размеры изображения")

    bottom_up = biHeight > 0
    height = abs(biHeight)

    #Длина строки дополняется до кратности 4
    row_size = ((biWidth * 3 + 3) // 4) * 4
    expected_size = bfOffBits + row_size * height

    if len(data) < expected_size:
        raise BMPError(f"Файл обрезан: ожидалось {expected_size} байт, получено {len(data)}")

    pixels = []
    for y in range(height):
        row_start = bfOffBits + y * row_size
        for x in range(biWidth):
            offset = row_start + x * 3
            b = data[offset]
            g = data[offset + 1]
            r = data[offset + 2]
            pixels.append((b, g, r))

    return biWidth, height, pixels, bottom_up


def write_bmp(path, width, height, pixels, bottom_up):
    row_size = ((width * 3 + 3) // 4) * 4
    padding = row_size - width * 3

    pixel_data = bytearray()
    for i in range(height):
        for j in range(width):
            b, g, r = pixels[i * width + j]
            pixel_data.extend((b, g, r))
        pixel_data.extend(b'\x00' * padding)

    #biHeight: положительный если bottom_up, отрицательный если top-down
    h_val = height if bottom_up else -height
    file_header = struct.pack("<2sIHHI", b'BM', 54 + len(pixel_data), 0, 0, 54)
    info_header = struct.pack("<IiiHHIIiiII", 40, width, h_val, 1, 24, 0, len(pixel_data), 2835, 2835, 0, 0)

    with open(path, "wb") as f:
        f.write(file_header)
        f.write(info_header)
        f.write(pixel_data)

def counting_sort_by_digit(keys, pixels, exp, frame_callback=None, frame_step=10000):
    n = len(keys)
    output_keys = [0] * n
    output_pixels = [None] * n
    count = [0] * 10

    for i in range(n):
        digit = (keys[i] // exp) % 10
        count[digit] += 1

    for i in range(1, 10):
        count[i] += count[i - 1]

    for i in range(n - 1, -1, -1):
        digit = (keys[i] // exp) % 10
        count[digit] -= 1
        pos = count[digit]
        output_keys[pos] = keys[i]
        output_pixels[pos] = pixels[i]

    #Копируем обратно
    for i in range(n):
        keys[i] = output_keys[i]
        pixels[i] = output_pixels[i]
        if frame_callback and (i + 1) % frame_step == 0:
            frame_callback(pixels)


def radix_sort_lsd(keys, pixels, frame_callback=None, frame_step=10000):
    if not keys:
        return
    max_key = max(keys)
    if max_key < 0:
        raise ValueError("Отрицательные ключи не поддерживаются алгоритмом LSD")

    exp = 1
    while max_key // exp > 0:
        counting_sort_by_digit(keys, pixels, exp, frame_callback, frame_step)
        exp *= 10
        #Сохраняем кадр после каждого разряда
        if frame_callback:
            frame_callback(pixels)

def main():
    if len(sys.argv) == 3 and not sys.argv[1].startswith('-'):
        bmp_path = sys.argv[1]
        out_path = sys.argv[2]

        if bmp_path.endswith('.in'):
            keys_path = bmp_path[:-3] + '.keys.txt'
        else:
            keys_path = bmp_path + '.keys.txt'

        bench = 1
        anim_dir = None
        anim_step = 10000
    else:
        #Ручной запуск через аргументы
        parser = argparse.ArgumentParser(description="Восстановление BMP сортировкой (LSD)")
        parser.add_argument("--bmp", required=True, help="Путь к перемешанному BMP")
        parser.add_argument("--keys", required=True, help="Путь к файлу ключей")
        parser.add_argument("--out", required=True, help="Путь для сохранения результата")
        parser.add_argument("--bench", type=int, default=1, help="Число повторов замера")
        parser.add_argument("--anim-dir", help="Директория для сохранения кадров анимации")
        parser.add_argument("--anim-step", type=int, default=10000, help="Сохранять кадр каждые K операций")

        args = parser.parse_args()

        bmp_path = args.bmp
        keys_path = args.keys
        out_path = args.out
        bench = args.bench
        anim_dir = args.anim_dir
        anim_step = args.anim_step

    try:
        #Чтение изображения
        width, height, pixels, bottom_up = read_bmp(bmp_path)

        #Чтение ключей
        with open(keys_path, "r") as f:
            lines = [line.strip() for line in f if line.strip()]

        if not lines:
            raise ValueError("Файл ключей пуст")

        n_keys = int(lines[0])
        keys = [int(x) for x in lines[1:]]

        if len(keys) != n_keys:
            raise ValueError(f"Заявлено ключей {n_keys}, а прочитано {len(keys)}")
        if len(keys) != len(pixels):
            raise ValueError(f"Несовпадение: ключей {len(keys)}, пикселей {len(pixels)}")

        #Настройка анимации
        frame_callback = None
        if anim_dir:
            os.makedirs(anim_dir, exist_ok=True)
            frame_counter = 0

            def save_frame(current_pixels):
                nonlocal frame_counter
                fname = os.path.join(anim_dir, f"frame_{frame_counter:04d}.bmp")
                write_bmp(fname, width, height, current_pixels, bottom_up)
                frame_counter += 1

            frame_callback = save_frame

        #Замеры или одиночный запуск
        if bench > 1:
            #ПРОГРЕВ
            for _ in range(3):
                k_warm = keys.copy()
                p_warm = pixels.copy()
                radix_sort_lsd(k_warm, p_warm)

            times = []
            checksum = 0

            #СЕРИЯ ЗАМЕРОВ
            for _ in range(bench):
                k_copy = keys.copy()
                p_copy = pixels.copy()

                t0 = time.perf_counter()
                radix_sort_lsd(k_copy, p_copy)
                t1 = time.perf_counter()

                times.append(t1 - t0)

                checksum = sum(k_copy)

            med = statistics.median(times)
            lo, hi = min(times), max(times)

            print(f"Медиана сортировки: {med * 1000:.3f} мс")
            print(f"Мин: {lo * 1000:.3f} мс, Макс: {hi * 1000:.3f} мс")
            print(f"Контрольная сумма (сумма ключей): {checksum}")

            #Сохраняем последний отсортированный массив для записи в файл
            final_keys, final_pixels = k_copy, p_copy
        else:
            final_keys, final_pixels = keys, pixels
            radix_sort_lsd(final_keys, final_pixels, frame_callback, anim_step)

        #Запись результата
        write_bmp(out_path, width, height, final_pixels, bottom_up)

        if len(sys.argv) != 3:
            print(f"Готово! Изображение сохранено в {out_path}")

    except (BMPError, ValueError, OSError) as e:
        err_msg = f"Ошибка: {e}"
        print(err_msg, file=sys.stderr) # Вывод в консоль для check.py

        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            bmp_name = sys.argv[1] if len(sys.argv) > 1 else "неизвестный_файл"
            with open("errors.log", "a", encoding="utf-8") as log_file:
                log_file.write(f"[{timestamp}] Входной файл: {bmp_name}\n")
                log_file.write(f"  Причина: {err_msg}\n")
                log_file.write("-" * 50 + "\n")
        except Exception:
            pass #Если не удалось записать лог, не роняем программу

        sys.exit(1)

    except Exception as e:
        err_msg = f"Непредвиденная ошибка: {e}"
        print(err_msg, file=sys.stderr)

        try:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            with open("errors.log", "a", encoding="utf-8") as log_file:
                log_file.write(f"[{timestamp}] {err_msg}\n")
                log_file.write("-" * 50 + "\n")
        except Exception:
            pass

        sys.exit(2)
if __name__ == "__main__":
    main()