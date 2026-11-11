"""
Which contents enter the sentiment analysis, and how their text is cleaned (İG-11)

Many collected texts carry no opinion about the stock. If they are scored they
pull every daily average towards 0 and drown the real signal, so they are left
out before scoring (they stay in `contents`, they just get no `sentiments` row):

    KAP       only the company's own special-situation notices (category 'ODA');
              routine notices (DG: general assembly, bond redemption ...,
              FR: financial reports, DKB) carry no direction
    news      all (already filtered for the company in fetch_news.py)
    comments  left out: spam/adverts (on YouTube any link counts as an advert; in
              Hisse.net posts links are news shared with an opinion, so they are
              removed before the checks), very short texts, thanks/praise for the
              video maker or a request for another video, unless the text also
              contains an opinion cue (price, target, buy/sell, profit/loss ...)

The rules were set by looking at the first labelled validation batch (200 rows);
their quality is checked on a second, independent batch.
"""
import html
import re

# ------------------------------------------------------------ selection --

SPAM = re.compile(r"https?://|www\.|udemy|kupon|indirim kodu|telegram|whatsapp|abone ol|link bio")
PRAISE = re.compile(
    r"teşekk|tesekk|teşekür|tesekur|tşk|tsk\b|sağ ?ol|sag ?ol|\bemek(?!li)|\bemeğ|\bemeg|\bemey|eline|elinize|"
    r"ellerine|ağzına|agzina|ağzınıza|yüreğ|yureg|minnettar|kralı|iyi ki var|huzur veren|eyvallah|"
    r"bahtiyar|anlatım|kaliteli|başarılar|selamlar|üstad|üstat|ustad|videolarınız|ilk beğeni|abone")
REQUEST = re.compile(
    r"yapabilir misiniz|yapabilirsiniz|yaparsanız|yapar mısınız|yapar misiniz|çekseniz|cekseniz|"
    r"yorumlarsanız|yorumlar mısınız|videosu gelecek|video çek|bir de \w+ yap|bekliyoruz videolarınızda")
OPINION = re.compile(
    r"hisse|aldım|alırım|alın\b|aldık|alım|sattım|satın|satış|sat\b|ekle|maliyet|lot\b|hedef|kâr|kar\b|"
    r"karı|zarar|kazan|kaybet|yüksel|düş|tavan|taban|temett|bedelsiz|bilanço|prim|zirve|dip\b|ralli|"
    r"uç|çök|batır|batar|fırsat|pahalı|ucuz|bekli|tut|\d")


def tr_lower(text):
    """Turkish-aware lower case (İ -> i, I -> ı)."""
    return text.replace("İ", "i").replace("I", "ı").lower()


# forum mobile-app footers ("<device> cihazımdan hisse.net mobile app kullanarak gönderildi.",
# "Tapatalk kullanarak iPhone aracılığıyla gönderildi", "Sent from my iPhone using Tapatalk")
SIGNATURE = re.compile(
    r"[^\n]{0,60}cihaz[ıi]mdan\s+hisse\.net mobile app\s+kullanarak g[öo]nderildi\.?"
    r"|(?:tapatalk|hisse\.net) kullanarak[^\n]{0,60}g[öo]nderildi\.?"
    r"|sent from[^\n]{0,60}using (?:tapatalk|hisse\.net)[^\n]*", re.I)
FORUM = "Hisse.net"


def comment_exclusion(text, source=None):
    """Reason why a comment is left out ('spam', 'short', 'praise', 'request'), or None.
    In forum posts links are removed first: there they are shared news, not adverts."""
    text = SIGNATURE.sub(" ", text or "")
    if source == FORUM:
        text = URL.sub(" ", text)
    low = tr_lower(" ".join(text.split()))
    if SPAM.search(low):
        return "spam"
    if len(re.sub(r"[\W_]+", "", low)) < 4:
        return "short"
    if len(low) < 200 and not OPINION.search(low):
        if PRAISE.search(low):
            return "praise"
        if REQUEST.search(low):
            return "request"
    return None


def exclusion(ctype, category, is_company_notice, text, source=None):
    """Reason why a content is not scored, or None if it enters the sentiment analysis."""
    if ctype == "kap":
        if is_company_notice != 1:
            return "market notice"
        if category != "ODA":
            return f"routine KAP ({category})"
        return None
    if ctype == "comment":
        return comment_exclusion(text, source)
    return None


# ------------------------------------------------------------- cleaning --

URL = re.compile(r"https?://\S+|www\.\S+")
MENTION = re.compile(r"@\w+")
REPEAT = re.compile(r"(\w)\1{2,}")                     # "çokkkk" -> "çokk"


def clean_text(text):
    """Model input (İG-11): links, forum app footers and @user names removed, '#' dropped (the word is kept),
    letters repeated 3+ times shortened, whitespace collapsed. Case and emoji are kept:
    cased models use the case, uncased tokenizers lower-case themselves."""
    text = html.unescape(text or "")
    text = SIGNATURE.sub(" ", text)
    text = URL.sub(" ", text)
    text = MENTION.sub(" ", text)
    text = text.replace("#", " ")
    text = REPEAT.sub(r"\1\1", text)
    return " ".join(text.split())
