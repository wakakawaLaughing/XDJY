from setuptools import setup

package_name = 'ros_process_monitor_py'

setup(
    name=package_name,
    version='0.1.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', [f'resource/{package_name}']),
        # Keep ROS package share under the ROS package name, not Python pkg name
        ('share/ament_index/resource_index/packages', ['resource/ros_process_monitor']),
        ('share/ros_process_monitor', ['package.xml']),
        ('share/ros_process_monitor/msg', ['msg/ProcessUsage.msg', 'msg/ProcessUsageArray.msg']),
        ('share/ros_process_monitor/config', ['config/process_config.json']),
    ],
    install_requires=['setuptools', 'psutil'],
    zip_safe=True,
    maintainer='dev',
    maintainer_email='dev@example.com',
    description='Publish CPU and memory usage for specified processes as ROS 2 messages',
    license='MIT',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'process_monitor_node = ros_process_monitor_py.process_monitor_node:main',
        ],
    },
)


