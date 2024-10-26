import os
from pyppeteer import launch
import aiohttp
from urllib import request
from PIL import Image
import platform
import zipfile
import datetime
import asyncio
import random
import cv2
import numpy as np
import base64
import io
import re
from playwright.async_api import Playwright, async_playwright
import ddddocr

# 传参获得已初始化的ddddocr实例
ocr = None
det = ddddocr.DdddOcr(show_ad=False, det=True)

# 支持的形状类型
supported_types = [
    "三角形",
    "正方形",
    "长方形",
    "五角星",
    "六边形",
    "圆形",
    "梯形",
    "圆环",
]
# 定义了支持的每种颜色的 HSV 范围
supported_colors = {
    "紫色": ([125, 50, 50], [145, 255, 255]),
    "灰色": ([0, 0, 50], [180, 50, 255]),
    "粉色": ([160, 50, 50], [180, 255, 255]),
    "蓝色": ([100, 50, 50], [130, 255, 255]),
    "绿色": ([40, 50, 50], [80, 255, 255]),
    "橙色": ([10, 50, 50], [25, 255, 255]),
    "黄色": ([25, 50, 50], [35, 255, 255]),
    "红色": ([0, 50, 50], [10, 255, 255]),
}


async def deleteSession(workList, uid):
    s = workList.get(uid, "")
    if s:
        await asyncio.sleep(60)
        del workList[uid]


async def logon_main( workList, uid, headless):
    # 判断账号密码错误
    async def isWrongAccountOrPassword(page, verify=False):
        try:
            # 定位元素使用 `locator` 方法
            element = page.locator('//*[@id="app"]/div/div[5]')

            # 检查元素是否存在
            if await element.count() > 0:
                # 获取文本内容
                text = await element.text_content()

                if text and "账号或密码不正确" in text:
                    if verify:
                        return True
                    await asyncio.sleep(2)
                    return await isWrongAccountOrPassword(page, verify=True)
            return False
        except Exception as e:
            print("isWrongAccountOrPassword " + str(e))
            return False

    # 判断验证码超时
    async def isStillInSMSCodeSentPage(page):
        try:
            # 尝试获取元素
            element = await page.locator('xpath=//*[@id="header"]/span[2]').element_handle(timeout=4)

            if element:
                # 获取元素的文本内容
                text = await page.evaluate("(element) => element.textContent", element)

                if text == "手机短信验证":
                    return True

            return False

        except Exception as e:
            print(f"is_still_in_sms_code_sent_page: {e}")
            return False

    # 判断验证码错误
    async def needResendSMSCode(page):
        try:
            # 使用 locator 获取元素的句柄
            element_handle = await page.locator('xpath=//*[@id="app"]/div/div[2]/div[2]/button').element_handle(timeout=4)
            if element_handle:
                # 使用 evaluate 获取元素的文本内容
                text = await page.evaluate("(element) => element.textContent", element_handle)
                if text == "获取验证码":
                    return True
            return False
        except Exception as e:
            print(f"need_resend_sms_code: {e}")
            return False

    async def isSendSMSDirectly(page):
        try:
            title = await page.title()
            if title in ['手机语音验证', '手机短信验证']:
                print('需要' + title)
                return True
            return False
        except Exception as e:
            print("isSendSMSDirectly " + str(e))
            return False

    usernum = workList[uid].account
    passwd = workList[uid].password
    sms_sent = False
    print(f"正在登录 {usernum} 的账号")

    # browser = await launch(
    #     {
    #         "executablePath": chromium_path,
    #         "headless": headless,
    #         "args": (
    #             "--no-sandbox",
    #             "--disable-setuid-sandbox",
    #             "--disable-dev-shm-usage",
    #             "--disable-gpu",
    #             "--disable-software-rasterizer",
    #         ),
    #     }
    # )
    # page = await browser.newPage()
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
            ]
        )


        page = await browser.new_page()

        await page.set_viewport_size({"width": 360, "height": 640})
        try:
            await page.goto("https://plogin.m.jd.com/login/login?appid=300&returnurl=https%3A%2F%2Fm.jd.com%2F&source=wq_passport",timeout=100000)
        except Exception as e:
            print("打开页面出错")
            workList[uid].status = "error"
            workList[uid].msg = "页面出错"
            print(e)
            return
        await typeuser(page, usernum, passwd)

        IN_SMS_TIMES = 0
        start_time = datetime.datetime.now()

        for i in range(100):
            try:
                now_time = datetime.datetime.now()
                print("循环检测中...")
                if (now_time - start_time).total_seconds() > 120:
                    print("进入超时分支")
                    workList[uid].status = "error"
                    workList[uid].msg = "登录超时"
                    break

                elif await page.locator("#searchWrapper").count()>0:
                    print("进入成功获取cookie分支")
                    workList[uid].cookie = await getCookie(page)
                    workList[uid].status = "pass"
                    break

                elif await isWrongAccountOrPassword(page):
                    print("进入账号密码不正确分支")

                    workList[uid].status = "error"
                    workList[uid].msg = "账号或密码不正确"
                    break

                elif await page.locator('//*[@id="small_img"]').count()>0:
                    print("进入过滑块分支")

                    workList[uid].status = "pending"
                    workList[uid].msg = "正在过滑块检测"
                    await verification(page)
                    await asyncio.sleep(3)

                elif await page.locator('//*[@id="captcha_modal"]/div/div[3]/button').count()>0:
                    print("进入点形状、颜色验证分支")
                    workList[uid].status = "pending"
                    workList[uid].msg = "正在过形状、颜色检测"
                    await verification_shape(page)
                    await asyncio.sleep(3)

                if not sms_sent:
                    if await page.locator('.sub-title').element_handle(timeout=3):
                        print("进入选择短信验证分支")
                        if not workList[uid].isAuto:
                            workList[uid].status = "SMS"
                            workList[uid].msg = "需要短信验证"

                            await sendSMS(page)
                            await asyncio.sleep(20)
                            await typeSMScode(page, workList, uid)
                            sms_sent = True

                        else:
                            workList[uid].status = "error"
                            workList[uid].msg = "自动续期时不能使用短信验证"
                            print("自动续期时不能使用短信验证")
                            break
                    elif await isSendSMSDirectly(page):
                        print("进入直接发短信分支")
                        if not workList[uid].isAuto:
                            workList[uid].status = "SMS"
                            workList[uid].msg = "需要短信验证"
                            await sendSMSDirectly(page)
                            await asyncio.sleep(20)
                            await typeSMScode(page, workList, uid)
                            sms_sent = True

                        else:
                            workList[uid].status = "error"
                            workList[uid].msg = "自动续期时不能使用短信验证"
                            print("自动续期时不能使用短信验证")
                            break
                else:
                    if await isStillInSMSCodeSentPage(page):
                        print("进入验证码错误分支")
                        IN_SMS_TIMES += 1
                        if IN_SMS_TIMES % 3 == 0:
                            workList[uid].SMS_CODE = None
                            workList[uid].status = "wrongSMS"
                            workList[uid].msg = "短信验证码错误，请重新输入"
                            await typeSMScode(page, workList, uid)

                    elif await needResendSMSCode(page):
                        print("进入验证码超时分支")
                        workList[uid].status = "error"
                        workList[uid].msg = "验证码超时，请重新开始"
                        break

                await asyncio.sleep(1)
            except Exception as e:
                await asyncio.sleep(2)
                # print("异常退出")
                # print(e)
                continue
                await browser.close()
                raise e

    print("任务完成退出")

    await browser.close()
    await deleteSession(workList, uid)
    return


async def typeuser(page, usernum, passwd):
    print("开始输入账号密码")
    await page.wait_for_selector(".J_ping.planBLogin")
    await page.click(".J_ping.planBLogin")
    # await page.type(
    #     "#username", usernum, {"delay": random.randint(60, 121)}
    # )
    # )
    await page.type("#username", usernum, delay=random.randint(100, 151))
    await page.type("#pwd", passwd, delay=random.randint(100, 151))

    # await page.type(
    #     "#pwd", passwd, {"delay": random.randint(100, 151)}
    # )
    await asyncio.sleep(random.randint(100/100, 500/100))
    await page.click(".policy_tip-checkbox")
    await asyncio.sleep(random.randint(100/100, 500/100))
    await page.click(".btn.J_ping.btn-active")
    await asyncio.sleep(random.randint(100/100, 500/100))


async def sendSMSDirectly(page):
    async def preSendSMS(page):
        await page.wait_for_selector('xpath=//*[@id="app"]/div/div[2]/div[2]/button')
        await asyncio.sleep(random.randint(1, 3))  # 使用 asyncio.sleep 进行随机等待
        elements = await page.locator('xpath=//*[@id="app"]/div/div[2]/div[2]/button').element_handles()
        if elements:
            await elements[0].click()
        await asyncio.sleep(3)  # 固定等待3秒

    await preSendSMS(page)
    print("开始发送验证码")
    try:
        while True:
            if await page.locator('xpath=//*[@id="captcha_modal"]/div/div[3]/div').element_handles():
                await verification(page)
            elif await page.locator('xpath=//*[@id="captcha_modal"]/div/div[3]/button').element_handles():
                await verification_shape(page)
            else:
                break
            await asyncio.sleep(3)  # 固定等待3秒

    except Exception as e:
        print(f"An error occurred: {e}")
        raise


async def sendSMS(page):
    async def preSendSMS(page):
        print("进行发送验证码前置操作")
        await page.locator('xpath=//*[@id="app"]/div/div[2]/div[2]/span/a').wait_for()

        await page.waitFor(random.randint(1, 3) * 1000)
        elements = await page.locator('xpath=//*[@id="app"]/div/div[2]/div[2]/span/a').element_handles()

        await elements[0].click()
        await page.locator('xpath=//*[@id="app"]/div/div[2]/div[2]/button').wait_for()
        await asyncio.sleep(random.randint(1, 3))

        elements = await page.locator('xpath=//*[@id="app"]/div/div[2]/div[2]/button').element_handles()
        if elements:
            await elements[0].click()
        # 等待 3 秒
        await asyncio.sleep(3)

    await preSendSMS(page)
    print("开始发送验证码")

    try:
        while True:
            captcha_modal = await page.locator('xpath=//*[@id="captcha_modal"]/div/div[3]/div').element_handles()
            captcha_button = await page.locator('xpath=//*[@id="captcha_modal"]/div/div[3]/button').element_handles()

            if captcha_modal:
                await verification(page)
            elif captcha_button:
                await verification_shape(page)
            else:
                break

            await asyncio.sleep(3)

    except Exception as e:
        print(f"An error occurred: {e}")
        raise


async def typeSMScode(page, workList, uid):
    print("开始输入验证码")

    async def get_verification_code(workList, uid):
        print("开始从全局变量获取验证码")
        retry = 60
        while not workList[uid].SMS_CODE and not retry < 0:
            await asyncio.sleep(1)
            retry -= 1
        if retry < 0:
            workList[uid].status = "error"
            workList[uid].msg = "输入短信验证码超时"
            return

        workList[uid].status = "pending"
        return workList[uid].SMS_CODE

    await page.locator('//*[@id="app"]/div/div[2]/div[2]/div/input').wait_for()
    code = await get_verification_code(workList, uid)
    if not code:
        return

    workList[uid].status = "pending"
    workList[uid].msg = "正在通过短信验证"
    input_elements = await page.locator('//*[@id="app"]/div/div[2]/div[2]/div/input').all()

    try:
        if input_elements:
            input_value = await input_elements[0].evaluate('(element) => element.value')
            if input_value:
                print("清除验证码输入框中已有的验证码")
                await page.evaluate(
                    '(element) => element.value = ""', input_elements[0]
                )

    except Exception as e:
        print("typeSMScode" + str(e))

    await input_elements[0].type(code)
    await page.locator('xpath=//*[@id="app"]/div/div[2]/a[1]').wait_for()
    await asyncio.sleep(random.randint(1, 3))
    elements = await page.locator('xpath=//*[@id="app"]/div/div[2]/a[1]').element_handles()
    if elements:
        await elements[0].click()
    await asyncio.sleep(random.randint(2, 3))


async def verification(page):
    print("开始过滑块")

    async def get_distance():
        img = cv2.imread("image.png", 0)
        template = cv2.imread("template.png", 0)
        img = cv2.GaussianBlur(img, (5, 5), 0)
        template = cv2.GaussianBlur(template, (5, 5), 0)
        bg_edge = cv2.Canny(img, 100, 200)
        cut_edge = cv2.Canny(template, 100, 200)
        img = cv2.cvtColor(bg_edge, cv2.COLOR_GRAY2RGB)
        template = cv2.cvtColor(cut_edge, cv2.COLOR_GRAY2RGB)
        res = cv2.matchTemplate(
            img, template, cv2.TM_CCOEFF_NORMED
        )
        value = cv2.minMaxLoc(res)[3][0]
        distance = (
            value + 10
        )
        return distance

    await page.wait_for_selector("#cpc_img")
    image_src = await page.locator("#cpc_img").evaluate('el => el.getAttribute("src")')
    request.urlretrieve(image_src, "image.png")
    width = await page.evaluate(
        '() => { return document.getElementById("cpc_img").clientWidth; }'
    )
    height = await page.evaluate(
        '() => { return document.getElementById("cpc_img").clientHeight; }'
    )
    image = Image.open("image.png")
    resized_image = image.resize((width, height))
    resized_image.save("image.png")
    template_src = await page.locator("#small_img").evaluate('el => el.getAttribute("src")')
    request.urlretrieve(template_src, "template.png")
    width = await page.evaluate(
        '() => { return document.getElementById("small_img").clientWidth; }'
    )
    height = await page.evaluate(
        '() => { return document.getElementById("small_img").clientHeight; }'
    )
    image = Image.open("template.png")
    resized_image = image.resize((width, height))
    resized_image.save("template.png")
    await asyncio.sleep(1)
    el = await page.query_selector(
        "#captcha_modal > div > div.captcha_footer > div > img"
    )
    box = await el.bounding_box()
    distance = await get_distance()
    await page.mouse.move(box["x"] + 10, box["y"] + 10)
    await page.mouse.down()
    await page.mouse.move(
        box["x"] + distance + random.uniform(3, 15), box["y"], steps=10
    )
    await asyncio.sleep(
        random.randint(1, 5)
    )
    await page.mouse.move(
        box["x"] + distance, box["y"], steps=10
    )
    await page.mouse.up()
    print("过滑块结束")


async def verification_shape(page):
    print("开始过颜色、形状验证")

    def get_shape_location_by_type(img_path, type: str):
        def sort_rectangle_vertices(vertices):
            vertices = sorted(vertices, key=lambda x: x[1])
            top_left, top_right = sorted(vertices[:2], key=lambda x: x[0])
            bottom_left, bottom_right = sorted(vertices[2:], key=lambda x: x[0])
            return [top_left, top_right, bottom_right, bottom_left]

        def is_trapezoid(vertices):
            top_width = abs(vertices[1][0] - vertices[0][0])
            bottom_width = abs(vertices[2][0] - vertices[3][0])
            return top_width < bottom_width

        img = cv2.imread(img_path)
        imgGray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        imgBlur = cv2.GaussianBlur(imgGray, (5, 5), 1)
        imgCanny = cv2.Canny(imgBlur, 60, 60)
        contours, hierarchy = cv2.findContours(
            imgCanny, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )
        for obj in contours:
            perimeter = cv2.arcLength(obj, True)
            approx = cv2.approxPolyDP(obj, 0.02 * perimeter, True)
            CornerNum = len(approx)
            x, y, w, h = cv2.boundingRect(approx)

            if CornerNum == 3:
                obj_type = "三角形"
            elif CornerNum == 4:
                if w == h:
                    obj_type = "正方形"
                else:
                    approx = sort_rectangle_vertices([vertex[0] for vertex in approx])
                    if is_trapezoid(approx):
                        obj_type = "梯形"
                    else:
                        obj_type = "长方形"
            elif CornerNum == 6:
                obj_type = "六边形"
            elif CornerNum == 8:
                obj_type = "圆形"
            elif CornerNum == 20:
                obj_type = "五角星"
            else:
                obj_type = "未知"

            if obj_type == type:
                center_x, center_y = x + w // 2, y + h // 2
                return center_x, center_y

        return None, None

    def get_shape_location_by_color(img_path, target_color):
        image = cv2.imread(img_path)
        hsv_image = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)

        lower, upper = supported_colors[target_color]
        lower = np.array(lower, dtype="uint8")
        upper = np.array(upper, dtype="uint8")

        mask = cv2.inRange(hsv_image, lower, upper)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for contour in contours:
            if cv2.contourArea(contour) > 100:
                M = cv2.moments(contour)
                if M["m00"] != 0:
                    cX = int(M["m10"] / M["m00"])
                    cY = int(M["m01"] / M["m00"])
                    return cX, cY

        return None, None

    def get_word(ocr, img_path):
        image_bytes = open(img_path, "rb").read()
        result = ocr.classification(image_bytes, png_fix=True)
        return result

    def rgba2rgb(rgb_image_path, rgba_img_path):
        rgba_image = Image.open(rgba_img_path)
        rgb_image = Image.new("RGB", rgba_image.size, (255, 255, 255))
        rgb_image.paste(rgba_image, (0, 0), rgba_image)
        rgb_image.save(rgb_image_path)

    def save_img(img_path, img_bytes):
        with Image.open(io.BytesIO(img_bytes)) as img:
            img.save(img_path)

    def get_img_bytes(img_src: str) -> bytes:
        img_base64 = re.search(r"base64,(.*)", img_src)
        if img_base64:
            base64_code = img_base64.group(1)
            img_bytes = base64.b64decode(base64_code)
            return img_bytes
        else:
            raise "image is empty"

    for i in range(5):
        await page.wait_for_selector("div.captcha_footer img")

        image_src = await page.locator("#cpc_img").evaluate('el => el.getAttribute("src")')
        # image_src = await page.Jeval(
        #     "#cpc_img", 'el => el.getAttribute("src")'
        # )
        request.urlretrieve(image_src, "shape_image.png")
        width = await page.evaluate(
            '() => { return document.getElementById("cpc_img").clientWidth; }'
        )
        height = await page.evaluate(
            '() => { return document.getElementById("cpc_img").clientHeight; }'
        )
        image = Image.open("shape_image.png")
        resized_image = image.resize((width, height))
        resized_image.save("shape_image.png")

        b_image = await page.query_selector("#cpc_img")
        b_image_box = await b_image.bounding_box()
        image_top_left_x = b_image_box["x"]
        image_top_left_y = b_image_box["y"]

        word_src = await page.locator("div.captcha_footer img").evaluate('el => el.getAttribute("src")')
        # word_src = await page.Jeval(
        #     "div.captcha_footer img", 'el => el.getAttribute("src")'
        # )
        word_bytes = get_img_bytes(word_src)
        save_img("rgba_word_img.png", word_bytes)
        rgba2rgb("rgb_word_img.png", "rgba_word_img.png")
        word = get_word(ocr, "rgb_word_img.png")

        button = await page.query_selector("div.captcha_footer button.sure_btn")
        # refresh_button = await page.query_selector("div.captcha_header img.jcap_refresh")
        # 找到刷新按钮
        refresh_button = await page.query_selector('.jcap_refresh')
        if word.find("色") > 0:
            target_color = word.split("请选出图中")[1].split("的图形")[0]
            if target_color in supported_colors:
                print(f"正在找{target_color}")
                center_x, center_y = get_shape_location_by_color(
                    "shape_image.png", target_color
                )
                if center_x is None and center_y is None:
                    print("识别失败，刷新")
                    await refresh_button.click()
                    await asyncio.sleep(random.uniform(2, 4))
                    continue
                x, y = image_top_left_x + center_x, image_top_left_y + center_y
                await page.mouse.click(x, y)
                await asyncio.sleep(random.uniform(0.5, 2))
                await button.click()
                await asyncio.sleep(random.uniform(0.3, 1))
                break
            else:
                print(f"不支持{target_color}，重试")
                await refresh_button.click()
                await asyncio.sleep(random.uniform(2, 4))
                continue

        elif word.find('依次') > 0:
            print(f'开始文字识别,点击中......')
            # 获取文字的顺序列表
            try:
                target_char_list = list(re.findall(r'[\u4e00-\u9fff]+', word)[1])
            except IndexError:
                print(f'识别文字出错,刷新中......')
                await refresh_button.click()
                await asyncio.sleep(random.uniform(2, 4))
                continue

            target_char_len = len(target_char_list)

            # 识别字数不对
            if target_char_len != 4:
                print(f'识别的字数不对,刷新中......')
                await refresh_button.click()
                await asyncio.sleep(random.uniform(2, 4))
                continue

            # 定义【文字, 坐标】的列表
            target_list = [[x, []] for x in target_char_list]

            # 获取大图的二进制
            background_locator = page.locator('#cpc_img')
            background_locator_src = await background_locator.get_attribute('src')
            background_locator_bytes = get_img_bytes(background_locator_src)
            bboxes = det.detection(background_locator_bytes)

            count = 0
            im = cv2.imread("shape_image.png")
            for bbox in bboxes:
                # 左上角
                x1, y1, x2, y2 = bbox
                # 做了一下扩大
                expanded_x1, expanded_y1, expanded_x2, expanded_y2 = expand_coordinates(x1, y1, x2, y2, 10)
                im2 = im[expanded_y1:expanded_y2, expanded_x1:expanded_x2]
                img_path = cv2_save_img('word', im2)
                image_bytes = open(img_path, "rb").read()
                result = ocr.classification(image_bytes, png_fix=True)
                if result in target_char_list:
                    for index, target in enumerate(target_list):
                        if result == target[0] and target[0] is not None:
                            x = x1 + (x2 - x1) / 2
                            y = y1 + (y2 - y1) / 2
                            target_list[index][1] = [x, y]
                            count += 1

            if count != target_char_len:
                print(f'文字识别失败,刷新中......')
                await refresh_button.click()
                await asyncio.sleep(random.uniform(2, 4))
                continue

            for char in target_list:
                center_x = char[1][0]
                center_y = char[1][1]
                # 得到网页上的中心点
                x, y = image_top_left_x + center_x, image_top_left_y + center_y
                # 点击图片
                await page.mouse.click(x, y)
                await asyncio.sleep(random.uniform(1, 2))

            # 点击确定
            await button.click()
            await asyncio.sleep(random.uniform(1, 3))
        else:
            shape_type = word.split("请选出图中的")[1]
            if shape_type in supported_types:
                print(f"正在找{shape_type}")
                if shape_type == "圆环":
                    shape_type = shape_type.replace("圆环", "圆形")
                center_x, center_y = get_shape_location_by_type(
                    "shape_image.png", shape_type
                )
                if center_x is None and center_y is None:
                    print(f"识别失败,刷新")
                    await refresh_button.click()
                    await asyncio.sleep(random.uniform(2, 4))
                    continue
                x, y = image_top_left_x + center_x, image_top_left_y + center_y
                await page.mouse.click(x, y)
                await asyncio.sleep(random.uniform(0.5, 2))
                await button.click()
                await asyncio.sleep(random.uniform(0.3, 1))
                break
            else:
                print(f"不支持{shape_type},刷新中......")
                await refresh_button.click()
                await asyncio.sleep(random.uniform(2, 4))
                continue
    print("过图形结束")


async def getCookie(page):
    cookies = await page.context.cookies()
    pt_key = ""
    pt_pin = ""
    for cookie in cookies:
        if cookie["name"] == "pt_key":
            pt_key = cookie["value"]
        elif cookie["name"] == "pt_pin":
            pt_pin = cookie["value"]
    ck = f"pt_key={pt_key};pt_pin={pt_pin};"
    print(f"登录成功 {ck}")
    return ck


async def download_file(url, file_path):
    timeout = aiohttp.ClientTimeout(total=60000)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as response:
            with open(file_path, "wb") as file:
                file_size = int(response.headers.get("Content-Length", 0))
                downloaded_size = 0
                chunk_size = 1024
                while True:
                    chunk = await response.content.read(chunk_size)
                    if not chunk:
                        break
                    file.write(chunk)
                    downloaded_size += len(chunk)
                    progress = (downloaded_size / file_size) * 100
                    print(f"已下载{progress:.2f}%...", end="\r")
    print("下载完成，进行解压安装....")

async def main(workList, uid, oocr):
    global ocr
    ocr = oocr
    headless = platform.system() != "Windows"
    await logon_main( workList, uid, headless)
    os.remove("image.png") if os.path.exists("image.png") else None
    os.remove("template.png") if os.path.exists("template.png") else None
    os.remove("shape_image.png") if os.path.exists("shape_image.png") else None
    os.remove("rgba_word_img.png") if os.path.exists("rgba_word_img.png") else None
    os.remove("rgb_word_img.png") if os.path.exists("rgb_word_img.png") else None
    print("登录完成")
    await asyncio.sleep(5)
def get_zero_or_not(v):
    if v < 0:
        return 0
    return v
def expand_coordinates(x1, y1, x2, y2, N):
    # Calculate expanded coordinates
    new_x1 = get_zero_or_not(x1 - N)
    new_y1 = get_zero_or_not(y1 - N)
    new_x2 = x2 + N
    new_y2 = y2 + N
    return new_x1, new_y1, new_x2, new_y2

def get_tmp_dir(tmp_dir:str = './tmp'):
    # 检查并创建 tmp 目录（如果不存在）
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)
    return tmp_dir
def cv2_save_img(img_name, img, tmp_dir:str = './tmp'):
    tmp_dir = get_tmp_dir(tmp_dir)
    img_path = os.path.join(tmp_dir, f'{img_name}.png')
    cv2.imwrite(img_path, img)
    return img_path