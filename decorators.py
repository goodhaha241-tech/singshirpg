from functools import wraps
import discord
from data_manager import get_user_data

def auto_defer(arg=None, *, reload_data: bool = False):
    """
    View 상호작용을 위한 데코레이터.
    - @auto_defer, @auto_defer(), @auto_defer(reload_data=True) 모든 형식을 지원합니다.
    - 유저 권한 확인 (author)
    - interaction.response.defer() 자동 호출
    - reload_data=True 시, get_user_data를 통해 self.user_data 갱신
    """
    # @auto_defer 형태로 사용되었을 경우 (arg에 함수가 들어옴)
    func = arg if callable(arg) else None

    def decorator(func):
        @wraps(func)
        async def wrapper(self, interaction: discord.Interaction, *args, **kwargs):
            # 1. 권한 확인
            # [수정] 지속성 뷰를 위해 self.author가 없는 경우 현재 유저로 설정
            if not hasattr(self, "author") or self.author is None:
                self.author = interaction.user

            if interaction.user.id != self.author.id:
                try:
                    await interaction.response.send_message("❌ 본인의 메뉴만 조작할 수 있습니다.", ephemeral=True)
                except discord.errors.InteractionResponded:
                    pass
                except discord.errors.NotFound:
                    pass
                return

            # 2. Defer 처리 (이미 응답되지 않은 경우에만)
            if not interaction.response.is_done():
                try:
                    await interaction.response.defer()
                except discord.errors.InteractionResponded:
                    pass
                except discord.errors.NotFound:
                    return
                except Exception as e:
                    print(f"Defer Error: {e}")
                    return

            # 3. 데이터 리로드
            should_reload = reload_data or (isinstance(arg, bool) and arg)
            if should_reload:
                self.user_data = await get_user_data(self.author.id, self.author.display_name)

            try:
                await func(self, interaction, *args, **kwargs)
            except discord.errors.NotFound:
                pass
            except Exception as e:
                raise e
        return wrapper

    if func:
        return decorator(func)
    return decorator