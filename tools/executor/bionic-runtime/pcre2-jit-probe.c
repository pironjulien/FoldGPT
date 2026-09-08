#define PCRE2_CODE_UNIT_WIDTH 8
#include <pcre2.h>
#include <stdio.h>
#include <string.h>

/* Android must actually execute generated JIT code. Interpreter fallback is a failure. */
int main(void) {
    char version[64] = {0};
    unsigned int jit = 0;
    if (pcre2_config(PCRE2_CONFIG_VERSION, version) < 0 ||
        pcre2_config(PCRE2_CONFIG_JIT, &jit) < 0 || jit != 1 ||
        strncmp(version, "10.47", 5) != 0) return 10;
    static const unsigned char pattern[] = "(?<=prefix:)(\\p{L}+)\\s+\\1";
    static const unsigned char subject[] = "prefix:caf\xc3\xa9 caf\xc3\xa9";
    int error = 0;
    PCRE2_SIZE offset = 0, size = 0;
    pcre2_code *code = pcre2_compile(pattern, PCRE2_ZERO_TERMINATED,
                                    PCRE2_UTF | PCRE2_UCP, &error, &offset, NULL);
    if (code == NULL) { fprintf(stderr, "compile=%d offset=%zu\n", error, offset); return 11; }
    int compiled = pcre2_jit_compile(code, PCRE2_JIT_COMPLETE);
    if (compiled != 0 || pcre2_pattern_info(code, PCRE2_INFO_JITSIZE, &size) != 0 || size == 0) {
        fprintf(stderr, "jit_compile=%d jit_size=%zu\n", compiled, size);
        pcre2_code_free(code); return 12;
    }
    pcre2_match_data *match = pcre2_match_data_create_from_pattern(code, NULL);
    if (!match) { pcre2_code_free(code); return 13; }
    int matched = pcre2_jit_match(code, subject, sizeof(subject) - 1, 0, 0, match, NULL);
    PCRE2_SIZE *vector = pcre2_get_ovector_pointer(match);
    int valid = matched == 2 && vector[0] == 7 && vector[1] == sizeof(subject) - 1;
    printf("{\"pcre2Version\":\"%s\",\"jitAvailable\":%u,\"jitBytes\":%zu,"
           "\"jitMatch\":%d,\"unicodeLookbehindBackreferencePassed\":%s}\n",
           version, jit, size, matched, valid ? "true" : "false");
    pcre2_match_data_free(match);
    pcre2_code_free(code);
    return valid ? 0 : 14;
}
