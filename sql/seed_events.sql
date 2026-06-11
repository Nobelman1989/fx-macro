-- داده اولیه شاخص‌ها — هماهنگ با EVENT_MAP در calendar_fetcher.py
INSERT INTO economic_events (event_code, country, currency, title, importance, unit, higher_is_hawkish) VALUES
('US_CPI_YOY',        'US', 'USD', 'CPI سالانه آمریکا',                3, '%',      TRUE),
('US_CORE_CPI_YOY',   'US', 'USD', 'Core CPI سالانه آمریکا',           3, '%',      TRUE),
('US_NFP',            'US', 'USD', 'اشتغال غیرکشاورزی (NFP)',          3, 'K',      TRUE),
('US_UNEMPLOYMENT',   'US', 'USD', 'نرخ بیکاری آمریکا',                3, '%',      FALSE),
('US_AHE_MOM',        'US', 'USD', 'رشد ماهانه دستمزد',                2, '%',      TRUE),
('US_GDP_QOQ_ADV',    'US', 'USD', 'GDP فصلی (Advance)',               3, '%',      TRUE),
('US_CORE_PCE_YOY',   'US', 'USD', 'Core PCE سالانه (شاخص هدف Fed)',   3, '%',      TRUE),
('US_JOBLESS_CLAIMS', 'US', 'USD', 'مدعیان اولیه بیکاری (هفتگی)',      2, 'K',      FALSE),
('US_RETAIL_MOM',     'US', 'USD', 'خرده‌فروشی ماهانه',                2, '%',      TRUE),
('US_ISM_MFG',        'US', 'USD', 'ISM Manufacturing PMI',            2, 'index',  TRUE),
('EU_CPI_FLASH_YOY',  'EU', 'EUR', 'تورم فلش منطقه یورو',              3, '%',      TRUE),
('GB_CPI_YOY',        'GB', 'GBP', 'تورم سالانه بریتانیا',             3, '%',      TRUE)
ON CONFLICT (event_code) DO NOTHING;
