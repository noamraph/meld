"""
A hatchling hook for setting the platform tag
"""

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version, build_data):
        if self.target_name == 'wheel':
            platform_tag = self.config['platform_tag']
            build_data['tag'] = f'py3-none-{platform_tag}'
