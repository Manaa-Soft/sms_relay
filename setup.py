from setuptools import setup, find_packages

with open("requirements.txt", "r") as f:
    install_requires = f.read().strip().split("\n")

setup(
    name="sms_relay",
    version="1.0.0",
    description="SMS Relay Gateway for Frappe/ERPNext",
    author="Manaa Soft",
    author_email="info@manaa-soft.com",
    packages=find_packages(),
    zip_safe=False,
    include_package_data=True,
    install_requires=install_requires,
)
