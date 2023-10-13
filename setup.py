from setuptools import setup, find_packages

setup(name='nanonet',
      version='1.0.0',
      description='Custom install of NanoNet',
      author='Tomer Cohen',
      url='https://github.com/BigHat-Biosciences/NanoNet',
      packages=find_packages(),
      install_requires=['tensorflow'])
