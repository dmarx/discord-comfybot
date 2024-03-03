from setuptools import setup, find_packages

setup(
    name="discord_bot",
    version="0.1.0",
    packages=find_packages(where='src'),
    package_dir={'': 'src'},
    entry_points={
        'console_scripts': [
            'discord-bot=discord_bot.bot:main',
        ],
    },
)
