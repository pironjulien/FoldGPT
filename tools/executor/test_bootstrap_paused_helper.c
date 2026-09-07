/* PC lifecycle fixture only. Never emits data or pretends to read a file. */
#include <unistd.h>
int main(void) { for (;;) pause(); }
