# code-loop v4

منهجية خفيفة لوكلاء البرمجة: أعلى نتيجة حقيقية، بأقل كود، أقل توكنز، وأقل مخاطرة.

الفكرة ليست أن نحشو الوكيل بموسوعة طب وفيزياء ورياضيات وتعلم آلة. الفكرة أن نعطيه نواة قرار
خبيرة: يعرف متى يتحرك بسرعة، متى يبطئ، متى يبحث، متى يتحقق، ومتى لا يكتب كودًا أصلًا.

## ماذا يفعل

`code-loop` يجعل الوكيل:

- يقلل البناء الزائد.
- يلمس النطاق المطلوب فقط.
- يفرق بين التعديل المحلي والتغيير عالي المخاطر.
- يعامل المدخلات الخارجية كحدود ثقة تحتاج تحققًا.
- يختار فحصًا حقيقيًا قبل إعلان الانتهاء.
- يفتح مساحة ابتكار فعلية، لكن يوسم الفرضيات ويطلب تجربة قابلة للتكذيب.
- يستدعي عمق المجال فقط عند الحاجة: أمن، ML، إحصاء، فيزياء، طب، تصميم، تخطيط.

## لماذا v4

v3 كانت خمسة أسئلة قوية. v4 تحولها إلى نظام أخف وأذكى:

| الطبقة | الغرض |
|---|---|
| `SKILL.md` | النواة السريعة: Fast Path، Expert Loop، Ladder، Risk Gate، Domain Router |
| `AGENTS.md` | نسخة مباشرة لأي وكيل يقرأ AGENTS.md مثل Codex |
| `references/` | عمق اختياري لا يستهلك السياق إلا عند الحاجة |
| `scripts/lint-instructions.py` | فحص يمنع تضخم التعليمات والأنماط الضعيفة |

## البنية

```text
code-loop/
├── SKILL.md
├── AGENTS.md
├── README.md
├── LICENSE
├── agents/openai.yaml
├── references/
│   ├── domain-router.md
│   ├── innovation-protocol.md
│   ├── risk-matrix.md
│   ├── verification.md
│   └── token-discipline.md
├── scripts/
│   └── lint-instructions.py
├── .cursor/rules/code-loop.md
├── .windsurf/rules/code-loop.md
└── .clinerules/code-loop.md
```

## التركيب

### Codex أو أي وكيل يدعم AGENTS.md

```bash
cp AGENTS.md /path/to/project/AGENTS.md
```

### Claude Code كـ Skill

داخل مشروع واحد:

```bash
mkdir -p /path/to/project/.claude/skills/code-loop
cp -r SKILL.md references scripts /path/to/project/.claude/skills/code-loop/
```

عالميًا:

```bash
mkdir -p ~/.claude/skills/code-loop
cp -r SKILL.md references scripts ~/.claude/skills/code-loop/
```

### Cursor / Windsurf / Cline

انسخ إحدى النسخ الجاهزة:

```bash
cp .cursor/rules/code-loop.md /path/to/project/.cursor/rules/code-loop.md
cp .windsurf/rules/code-loop.md /path/to/project/.windsurf/rules/code-loop.md
cp .clinerules/code-loop.md /path/to/project/.clinerules/code-loop.md
```

## الفلسفة المختصرة

1. افهم أقل سياق يكفي.
2. استخدم الموجود قبل كتابة الجديد.
3. اكتب أقل كود يحقق نتيجة قابلة للتحقق.
4. لا توسع النطاق.
5. قيّم المخاطر قبل التنفيذ.
6. عند الابتكار: افصل المعروف عن المفترض عن الفرضي.
7. تحقق بفحص يمكن أن يفشل.
8. اختصر الكلام بقدر ما تسمح به المخاطرة.

## المجالات عالية الخبرة

v4 لا يدعي أن الوكيل طبيب أو فيزيائي أو إحصائي دائمًا. بدلًا من ذلك يوجهه إلى أسئلة الخبراء:

- في الطب/القانون/المال: استخدم مصادر حديثة واذكر عدم اليقين.
- في ML والإحصاء: حدد الهدف، baseline، metric، leakage، uncertainty.
- في الفيزياء والهندسة: افحص الوحدات، الحدود، التقريبات، والحجم التقريبي.
- في الأمن: افحص الصلاحيات، الأسرار، الحقن، السجلات، وسوء الاستخدام.
- في التصميم: ابنِ workflow حقيقيًا وتحقق بصريًا.
- في الابتكار: ولّد 2-4 أفكار مختلفة، اختر الأرخص اختبارًا، واذكر ما الذي يجعلها خاطئة.

التفاصيل موجودة في `references/domain-router.md` ولا تُقرأ إلا عند الحاجة.

## مساحة الابتكار بلا هلوسة

عند طلب اختراع أو فكرة جديدة، يستخدم v4 بروتوكولًا علميًا:

```text
Target:
Known:
Assumptions:
Candidates:
Best experiment:
Failure signals:
Next step:
```

هذا يسمح للوكيل أن يكون خلاقًا، لكن لا يسمح له أن يبيع التخمين كحقيقة. التفاصيل في
`references/innovation-protocol.md`.

## فحص الحزمة

```bash
python scripts/lint-instructions.py
```

الفحص يتأكد من:

- وجود الملفات المرجعية الأساسية.
- أن `SKILL.md` و`AGENTS.md` بقيا خفيفين.
- عدم وجود أنماط تعليمات ضعيفة أو مخلفات Python cache في النصوص.
- أن النواة تشير إلى المراجع المطلوبة.

## ملاحظات نشر

`code-loop.zip` أرشيف توزيع مولد من ملفات v4 الحالية. عند تعديل الحزمة، أعد تشغيل الفحص ثم
أعد توليد الأرشيف من الجذر بدون تضمين أي أرشيفات قديمة داخله.

## الترخيص

MIT.
