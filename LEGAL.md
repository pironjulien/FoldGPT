# Legal Compliance & Intellectual Property Notice: FoldGPT

## 1. Overview & Nature of the Project
**FoldGPT** is an independent, open-source orchestration wrapper and display compatibility layer designed exclusively for Android foldable devices (such as the Samsung Galaxy Z Fold series). 

The project aims solely to provide **hardware interoperability and display adaptation** between standard Linux applications and the unique dual-screen form factor of foldable Android devices, without altering any proprietary application binaries or bypassing system security mechanisms.

---

## 2. Open Source Licensing & Upstream Attribution
- **Wrapper Architecture**: FoldGPT's host orchestration scripts, launcher interface, and container scaffolding are distributed under the **GNU General Public License v3.0 (GPL-3.0)** or compatible open-source licenses.
- **Termux & PRoot Components**: Termux, PRoot, and Termux:X11 are copyright of their respective authors and are used in accordance with their respective open-source licenses (GPLv3).
- **Compliance Guarantee**: No proprietary code has been introduced into any GPL-licensed components, and full source code for any modified build of open-source utilities will be made publicly accessible under the terms of the GPL-3.0.

---

## 3. Strict Proprietary Binary Policy (No Bundling, No Cracking, No Modification)
- **Zero Redistribution**: FoldGPT **does NOT distribute, host, mirror, or repackage** any proprietary binaries, assets, or software owned by OpenAI, Inc.
- **Unmodified Upstream Source**: The official ChatGPT desktop Linux application (`.deb` / ARM64 package) is downloaded **directly by the end-user's device** from OpenAI's official Debian package repository (`https://learn.chatgpt.com/docs/linux/linux-app`).
- **Binary Integrity**: The application binary is executed in its **100% authentic, unmodified state**. FoldGPT does not patch binary files, alter symbol tables, bypass licensing checks, or tamper with signature verification (`dpkg -V` verified).
- **Environment Compatibility Layer**: Interoperability is achieved purely via user-space environment emulation (standard glibc dynamic linker redirection via `LD_PRELOAD` in userspace), which bridges kernel system call interfaces without modifying the target application code.

---

## 4. International Legal Framework for Interoperability

### European Union (EU)
- **Directive 2009/24/EC (Legal Protection of Computer Programs)**:
  - **Article 5(3)**: The person having a right to use a copy of a computer program shall be entitled, without the authorization of the rightholder, to observe, study or test the functioning of the program in order to determine the ideas and principles which underlie any element of the program.
  - **Article 6 (Decompilation for Interoperability)**: Reproduction of the code and translation of its form are explicitly permitted where indispensable to obtain the information necessary to achieve the interoperability of an independently created computer program with other programs, provided the information is not used for purposes other than achieving interoperability.

### United States (US)
- **17 U.S.C. § 1201(f) (DMCA Reverse Engineering Exception)**:
  - Permits reverse engineering and circumvention solely for the purpose of identifying and analyzing elements of the program that are necessary to achieve interoperability of an independently created computer program with other programs.
- **Fair Use Doctrine (17 U.S.C. § 107)**:
  - Research, technical testing, educational demonstration, and hardware compatibility across computing architectures constitute transformative fair use.

---

## 5. Device Security & Integrity (Samsung Knox & Android Compatibility)
- **Knox Warranty Bit Intact (0x0)**: FoldGPT requires **zero root privileges** (`su`), zero kernel modifications, and zero bootloader unlocking. The device warranty bit remains pristine at `0x0`.
- **SELinux Enforcing**: FoldGPT operates entirely within standard Android user-space sandboxes (`PRoot`). Android SELinux policies remain strictly in `Enforcing` mode.
- **Zero Exploits**: No vulnerability, privilege escalation, or security vulnerability is utilized or required.

---

## 6. Trademarks & Brand Disclaimer
- **"ChatGPT"**, **"OpenAI"**, and associated logos are registered trademarks of OpenAI, Inc.
- **"Samsung"**, **"Galaxy Z Fold"**, and **"One UI"** are registered trademarks of Samsung Electronics Co., Ltd.
- **"Google"**, **"Gemini"**, and **"Android"** are registered trademarks of Google LLC.
- FoldGPT is an independent research project and is **not** endorsed, sponsored, affiliated with, or certified by OpenAI, Samsung, or Google.
