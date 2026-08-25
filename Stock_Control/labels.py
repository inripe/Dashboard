# -*- coding: utf-8 -*-
"""
Bilingual labels, and the IN / OUT prefix on every movement.

Store staff read the movement name under pressure. Putting the direction first
means they never have to remember whether "Returned" adds or removes stock.
"""

# movement -> (direction, arabic)
MOVES = {
    "Received":                  ("IN",  "استلام"),
    "Customs / Loss":            ("OUT", "فقد في الجمارك"),
    "Scrap":                     ("OUT", "إتلاف"),
    "To Courier":                ("OUT", "تسليم للمندوب"),
    "Orders Assigned":           ("",    "طلبات مخصصة"),
    "Courier Handover":          ("",    "تسليم الطلبات للمندوب"),
    "Delivered":                 ("OUT", "تم التوصيل"),
    "Returned":                  ("IN",  "مرتجع"),
    "Return to Saleable":        ("IN",  "إرجاع للمخزون"),
    "Return to Scrap":           ("OUT", "إرجاع للإتلاف"),
    "Count Adjustment - Add":    ("IN",  "تسوية جرد - زيادة"),
    "Count Adjustment - Remove": ("OUT", "تسوية جرد - نقص"),
}

UI = {
    "What happened?":       "ماذا حدث؟",
    "Which shipment?":      "أي شحنة؟",
    "Which item?":          "أي صنف؟",
    "How many boxes?":      "كم صندوق؟",
    "Courier":              "المندوب",
    "How many orders?":     "كم طلب؟",
    "Why?":                 "السبب",
    "Note (optional)":      "ملاحظة (اختياري)",
    "Check before saving":  "راجع قبل الحفظ",
    "Save":                 "حفظ",
    "Start again":          "ابدأ من جديد",
    "Today":                "اليوم",
    "Void":                 "إلغاء",
    "Sign in":              "تسجيل الدخول",
    "Sign out":             "تسجيل الخروج",
    "User":                 "المستخدم",
    "Password":             "كلمة السر",
    "Market":               "السوق",
    "Available to sell":    "متاح للبيع",
    "With couriers":        "لدى المندوبين",
    "Open shipments":       "شحنات مفتوحة",
    "Oldest stock":         "أقدم مخزون",
    "Orders outstanding":   "طلبات معلقة",
    "Exceptions":           "استثناءات",
    "Ready to dispatch":    "جاهز للتوزيع",
    "Short":                "نقص",
    "Excluded":             "مستبعد",
    "boxes in store":       "صندوق في المخزن",
    "still Inripe stock":   "ما زال مخزون إنرايب",
    "not fully cleared":    "لم تُصفَّ بالكامل",
    "days since arrival":   "يوم منذ الوصول",
    "with couriers":        "لدى المندوبين",
    "need action":          "تحتاج إجراء",
}

ARROW = {"IN": "\u2193", "OUT": "\u2191", "": "\u00b7"}   # down = in, up = out


def move(name, arabic=True):
    """'IN  Received / استلام' - direction first, so it cannot be misread."""
    d, ar = MOVES.get(name, ("", ""))
    head = f"{ARROW[d]} {d}  " if d else ""
    return f"{head}{name}" + (f"  /  {ar}" if arabic and ar else "")


def t(key, arabic=True):
    ar = UI.get(key)
    return f"{key}  /  {ar}" if arabic and ar else key


def direction(name):
    return MOVES.get(name, ("", ""))[0]
