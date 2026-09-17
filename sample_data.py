from __future__ import annotations

SAMPLE_WEBAPP_ID = "1937084629516193794"

SAMPLE_SCHEMA = {
    "webappId": SAMPLE_WEBAPP_ID,
    "webappName": "Flux Kontext单图模式",
    "appName": "Flux Kontext单图模式",
    "coverUrl": "https://rh-images.xiaoyaoyou.com/de0db6f2564c8697b07df55a77f07be9/output/ComfyUI_00038_sffft_1742964027.png",
    "statisticsInfo": {
        "likeCount": "138",
        "downloadCount": "0",
        "useCount": "34545",
        "pv": "0",
        "collectCount": "498",
    },
    "nodeInfoList": [
        {
            "nodeId": "39",
            "nodeName": "LoadImage",
            "fieldName": "image",
            "fieldValue": "example.png",
            "fieldData": '[["example.png"], {"image_upload": true}]',
            "fieldType": "IMAGE",
            "description": "上传图像",
            "descriptionEn": "Upload image",
        },
        {
            "nodeId": "37",
            "nodeName": "RH_ComfyFluxKontext",
            "fieldName": "model",
            "fieldValue": "flux-kontext-pro",
            "fieldData": '[{"name":"flux-kontext-pro","index":"flux-kontext-pro","description":"flux-kontext-pro 模型（默认）"},{"name":"flux-kontext-max","index":"flux-kontext-max","description":"flux-kontext-max 模型"}]',
            "fieldType": "LIST",
            "description": "模型切换",
            "descriptionEn": "Model switch",
        },
        {
            "nodeId": "37",
            "nodeName": "RH_ComfyFluxKontext",
            "fieldName": "aspect_ratio",
            "fieldValue": "match_input_image",
            "fieldData": '["match_input_image","1:1","16:9","9:16","4:3","3:4"]',
            "fieldType": "LIST",
            "description": "输出比例",
            "descriptionEn": "Aspect ratio",
        },
        {
            "nodeId": "52",
            "nodeName": "RH_Translator",
            "fieldName": "prompt",
            "fieldValue": "给这个女人的发型变成齐耳短发",
            "fieldData": '["STRING", {"default": "", "multiline": true}]',
            "fieldType": "STRING",
            "description": "图像编辑文本输入框",
            "descriptionEn": "Image editing text input box",
        },
        {
            "nodeId": "37",
            "nodeName": "RH_ComfyFluxKontext",
            "fieldName": "seed",
            "fieldValue": "0",
            "fieldData": '["INT", {"default": 0}]',
            "fieldType": "INT",
            "description": "随机种子",
            "descriptionEn": "Seed",
        },
    ],
    "covers": [
        {
            "url": "https://rh-images.xiaoyaoyou.com/de0db6f2564c8697b07df55a77f07be9/output/ComfyUI_00038_sffft_1742964027.png"
        }
    ],
}
