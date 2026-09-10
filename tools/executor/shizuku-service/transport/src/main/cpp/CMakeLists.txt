cmake_minimum_required(VERSION 3.22.1)
project(foldgpt_shizuku_transport C)
add_library(foldgpt_shizuku_transport SHARED spawn.c)
target_compile_features(foldgpt_shizuku_transport PRIVATE c_std_11)
target_compile_options(foldgpt_shizuku_transport PRIVATE -Wall -Wextra -Werror -fstack-protector-strong)
target_link_options(foldgpt_shizuku_transport PRIVATE -Wl,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384)

# Historical qualification inventories remain unchanged unless the app launch
# contract is selected explicitly. Production also has a standalone pinned recipe.
option(FOLDGPT_BUILD_APP_TRANSPORT "Build the separate Android app owner transport" OFF)
if(FOLDGPT_BUILD_APP_TRANSPORT)
    add_library(foldgpt_app_transport SHARED app-spawn.c)
    target_compile_features(foldgpt_app_transport PRIVATE c_std_11)
    target_compile_options(foldgpt_app_transport PRIVATE -Wall -Wextra -Werror -fstack-protector-strong)
    target_link_options(foldgpt_app_transport PRIVATE -Wl,--no-undefined,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384)
endif()

# Standard Bionic shared library packaged with our signed APK. It is only
# selected by an attested deployment; bundling it does not alter the launcher.
get_filename_component(FOLDGPT_CWD_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../../../../bionic-cwd" REALPATH)
add_library(foldgpt_bionic_cwd SHARED "${FOLDGPT_CWD_DIR}/cwd.c")
target_compile_features(foldgpt_bionic_cwd PRIVATE c_std_11)
target_compile_options(foldgpt_bionic_cwd PRIVATE -Wall -Wextra -Werror -fvisibility=hidden -fstack-protector-strong)
target_link_options(foldgpt_bionic_cwd PRIVATE
    -Wl,--as-needed,--no-undefined,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384
    "-Wl,--version-script=${FOLDGPT_CWD_DIR}/exports.map")
