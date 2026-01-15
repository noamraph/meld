if is_wheel
  python_path = 'python'
else
  python_path = '/usr/bin/python3'
endif

configure_file(
    input: 'meld',
    output: 'meld',
    command: ['../meson_shebang_normalisation.py', '@INPUT@', '@OUTPUT@', python_path],
    install_dir: bindir,
)
