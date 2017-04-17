from setuptools import (
    setup,
    find_packages,
    )


install_requires = [
    'elasticsearch',
    'elasticsearch-dsl==0.0.8',
    'nefertari',
    ]


setup(
    name='nefertari_es',
    version='0.1',
    description='elasticsearch engine for nerfertari',
    classifiers=[
        "Programming Language :: Python",
        "Programming Language :: Python :: 2",
        "Programming Language :: Python :: 2.7",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.4",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        "Topic :: Database",
        "Topic :: Database :: Database Engines/Servers",
    ],
    author='Ramses',
    author_email='hello@ramses.tech',
    url='https://github.com/ramses-tech/nefertari-es',
    keywords='web wsgi bfg pylons pyramid rest elasticsearch',
    packages=find_packages(),
    include_package_data=True,
    zip_safe=False,
    install_requires=install_requires,
)
