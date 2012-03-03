try:
    from setuptools import setup
except:
    from distutils.core import setup

setup(
    name='ht',
    version='1.0.0',
    author='Yuri Karabatov',
    author_email='karabatov@gmail.com',
    url='https://github.com/karabatov/ht',
    py_modules=['ht'],
    entry_points={
        'console_scripts': [
            'ht = ht:_main',
        ],
    },
)
