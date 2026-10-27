# غرفة العمليات — اعتماد العنوان الجديد وخطوات محركات البحث

التاريخ: 2026-10-27
المشروع الوحيد: Home Organization Ideas
المستودع: Fadhel-docom/auto-blog — الفرع main

## العنوان الجديد

https://home-organization-ideas.pages.dev/

صاحب المشروع أفاد أن العنوان الجديد أصبح يعمل. يجب على Claude استخدام هذا العنوان في فحوص Cloudflare Pages والعمل الحالي، والتحقق بنفسه من الاستجابة الفعلية قبل إعلان النجاح:
- الصفحة الرئيسية: https://home-organization-ideas.pages.dev/
- خريطة الموقع: https://home-organization-ideas.pages.dev/sitemap.xml
- robots: https://home-organization-ideas.pages.dev/robots.txt

إذا ظهر خطأ، افحص آخر deployment وسبب الخطأ الجذري ثم أصلحه، لا تكتف بإخفاء العرض. وثّق السبب والإصلاح ونتائج الفحص في غرفة العمليات.

## تعليمات صريحة إلى Claude

1. اعتمد عنوان Cloudflare أعلاه في فحوص النسخة الجديدة والروابط الخاصة بها فوراً.
2. لا تغيّر إعداد GitHub Pages الأساسي أو baseURL في config.toml؛ يجب أن يبقى https://fadhel-docom.github.io/auto-blog/ ما دام GitHub Pages هو العنوان الأصلي الذي نحافظ عليه.
3. لا تضع عنوان Cloudflare المؤقت في canonical أو sitemap أو robots أو ملفات إنتاج GitHub Pages، ولا تكسر حارس SEO في .github/workflows/site_deploy.yml.
4. لا تشترِ نطاقاً ولا تطلب من المستخدم شراء نطاق.
5. بعد التحقق من الصفحة وخريطة الموقع وrobots، افحص الروابط الداخلية والروابط المطلقة وأي إعداد يسبب 404 أو يمنع الزحف. لا تغيّر العنوان الأساسي للموقع أو توجيهات SEO دون دليل واضح.
6. سجّل ما تغيّر، ونتائج التحقق، وأي خطوة تحتاج تدخلاً يدوياً من المستخدم.

## Google Search Console

- الخاصية القديمة المسجلة كـ owner: https://fadhel-docom.github.io/auto-blog/
- تمت إضافة خاصية URL-prefix جديدة بنجاح: https://home-organization-ideas.pages.dev/ . الإضافة وحدها لا تعني أن الملكية تم التحقق منها.
- بعد التحقق من ملكية الخاصية الجديدة، قدّم https://home-organization-ideas.pages.dev/sitemap.xml وتحقق من حالة الخريطة. لا تحذف الخاصية القديمة ولا تغيّرها؛ حافظ عليها لتتبع عنوان GitHub Pages.
- لا تعلن نجاح التحقق أو إرسال الخريطة قبل التأكد من نتائج الأدوات.

## Bing Webmaster Tools

- الخاصية القديمة المسجلة والمتحقق منها: https://fadhel-docom.github.io/auto-blog/
- لا توجد حالياً خاصية مسجلة لعنوان Cloudflare الجديد في قائمة المواقع المتاحة عبر التكامل.
- يجب إضافة https://home-organization-ideas.pages.dev/ إلى Bing Webmaster Tools والتحقق من الملكية أولاً، ثم إرسال https://home-organization-ideas.pages.dev/sitemap.xml بعد التأكد من أن الخريطة متاحة وصحيحة.
- حافظ على خاصية GitHub Pages القديمة؛ لا تحذفها.

## حالة التحقق عند إنشاء هذه الملاحظة

محاولات فتح عنوان Cloudflare و/sitemap.xml و/robots.txt عبر أداة الفحص المتاحة لم تُرجع محتوى يمكن التحقق منه؛ لذلك لا نعتبر الفحص التقني مؤكداً بعد. المطلوب من Claude فحص مباشر من سجلات النشر والمتصفح/الطرفية المتاحة وتوثيق النتيجة.

## تنبيه SEO

لا يُنقل canonical أو sitemap من GitHub Pages إلى Cloudflare لمجرد أن العنوان الجديد يعمل. أولاً تحقّق من الهدف النهائي للموقع، واستمر في حماية الفهرسة الحالية. إرسال sitemap أو إضافة property لا يضمن الفهرسة الفورية.